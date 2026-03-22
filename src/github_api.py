"""GitHub API interactions"""

import json
import asyncio
from js import fetch, Headers, Object
from pyodide.ffi import to_js
from cache import get_timeline_cache, set_timeline_cache, set_rate_limit_data


async def fetch_with_headers(url, headers=None, token=None):
    """Helper to fetch with proper header handling using pyodide.ffi.to_js"""
    if not headers:
        headers = {}
        
    if 'User-Agent' not in headers:
        headers['User-Agent'] = 'PR-Tracker/1.0'        
    if token:
        headers['Authorization'] = f'Bearer {token}'

    options = to_js({
        "method": "GET",
        "headers": headers
    }, dict_converter=Object.fromEntries)
    
    response = await fetch(url, options)
    
    # Log GitHub API call with rate limit information
    # Check if URL starts with GitHub API domain for logging purposes only
    if url.startswith('https://api.github.com/'):
        rate_limit = response.headers.get('x-ratelimit-limit')
        rate_remaining = response.headers.get('x-ratelimit-remaining')
        rate_reset = response.headers.get('x-ratelimit-reset')

        if rate_limit and rate_remaining:
            set_rate_limit_data(rate_limit, rate_remaining, rate_reset)
            
        print(f"GitHub API: {url} | Status: {response.status} | Rate Limit: {rate_remaining}/{rate_limit} remaining | Reset: {rate_reset}")
    
    return response


async def fetch_open_conversations_count(owner, repo, pr_number, token=None):
    """
    Fetch count of unresolved review conversations (threads) using GitHub GraphQL API.
    
    Supports pagination to handle PRs with more than 100 review threads.
    
    Args:
        owner: Repository owner
        repo: Repository name
        pr_number: Pull request number
        token: Optional GitHub token for authentication
        
    Returns:
        int: Count of unresolved conversations, or 0 if error occurs
    """
    graphql_url = "https://api.github.com/graphql"
    
    # GraphQL query to fetch review threads with their resolved status and pagination
    query = """
    query($owner: String!, $repo: String!, $prNumber: Int!, $cursor: String) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $prNumber) {
          reviewThreads(first: 100, after: $cursor) {
            nodes {
              isResolved
            }
            pageInfo {
              hasNextPage
              endCursor
            }
          }
        }
      }
    }
    """
    
    headers = {
        'Accept': 'application/vnd.github+json',
        'Content-Type': 'application/json',
        'User-Agent': 'PR-Tracker/1.0'
    }
    
    if token:
        headers['Authorization'] = f'Bearer {token}'
    
    unresolved_count = 0
    cursor = None
    has_next_page = True
    
    try:
        # Paginate through all review threads
        while has_next_page:
            variables = {
                "owner": owner,
                "repo": repo,
                "prNumber": pr_number,
                "cursor": cursor
            }
            
            # Make GraphQL request
            options = to_js({
                "method": "POST",
                "headers": headers,
                "body": json.dumps({"query": query, "variables": variables})
            }, dict_converter=Object.fromEntries)
            
            response = await fetch(graphql_url, options)
            
            # Log GraphQL API call
            rate_limit = response.headers.get('x-ratelimit-limit')
            rate_remaining = response.headers.get('x-ratelimit-remaining')
            rate_reset = response.headers.get('x-ratelimit-reset')
            if rate_limit and rate_remaining:
                set_rate_limit_data(rate_limit, rate_remaining, rate_reset)
                
            print(f"GitHub GraphQL API: Status: {response.status} | Rate Limit: {rate_remaining}/{rate_limit} remaining")
            
            if response.status != 200:
                print(f"Warning: GraphQL API returned status {response.status}")
                return unresolved_count  # Return count from previous pages
            
            result = (await response.json()).to_py()
            
            # Check for GraphQL errors
            if 'errors' in result:
                print(f"GraphQL errors: {result['errors']}")
                return unresolved_count  # Return count from previous pages
            
            # Extract unresolved conversations count from this page
            pull_request = result.get('data', {}).get('repository', {}).get('pullRequest')
            if not pull_request:
                print(f"Warning: No PR data in GraphQL response for {owner}/{repo}#{pr_number}")
                return unresolved_count
            
            review_threads_data = pull_request.get('reviewThreads', {})
            threads = review_threads_data.get('nodes', [])
            page_info = review_threads_data.get('pageInfo', {})
            
            # Count unresolved threads in this page
            unresolved_count += sum(1 for thread in threads if not thread.get('isResolved', False))
            
            # Check if there are more pages
            has_next_page = page_info.get('hasNextPage', False)
            cursor = page_info.get('endCursor')
            
            print(f"PR #{pr_number}: Page has {len(threads)} threads, {unresolved_count} total unresolved so far")
        
        print(f"PR #{pr_number}: Found {unresolved_count} total unresolved conversations")
        return unresolved_count
        
    except Exception as e:
        print(f"Error fetching open conversations for PR #{pr_number}: {str(e)}")
        return unresolved_count  # Return partial count if available


async def fetch_pr_data(owner, repo, pr_number, token=None, etag=None):
    """
    Fetch PR data from GitHub API with parallel requests for optimal performance.
    
    Optimizations applied:
    - Conditional requests (ETags): Avoid fetching if data hasn't changed
    - Files list is NOT fetched since PR details already include 'changed_files' count
    - Checks, compare, and reviews API calls are made in parallel for efficiency
    """
    headers = {
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28'
    }
    
    if etag:
        headers['If-None-Match'] = etag
        
    try:
        # Fetch PR details first (needed for head SHA)
        pr_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
        pr_response = await fetch_with_headers(pr_url, headers, token)
        
        # Handle 304 Not Modified
        if pr_response.status == 304:
            print(f"GitHub API: PR #{pr_number} returned 304 Not Modified (Fast-path)")
            return {'not_modified': True}
            
        if pr_response.status == 404:
            return {'not_found': True}

        if pr_response.status != 200:
            return None
            
        pr_data = (await pr_response.json()).to_py()
        
        # Extract new ETag for storage
        new_etag = pr_response.headers.get('etag')

        # Prepare URLs for parallel fetching
        # We MUST NOT send If-None-Match to these secondary calls based on the PR etag,
        # as each endpoint has its own etag logic. We just want to clear headers.
        secondary_headers = {
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28'
        }
        # Note: We don't fetch files list since pr_data already includes 'changed_files' count
        # Reviews are fetched here to extract per-reviewer approval data (login + avatar)
        checks_url = f"https://api.github.com/repos/{owner}/{repo}/commits/{pr_data['head']['sha']}/check-runs"
        reviews_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/reviews?per_page=100"
        
        # Extract base and head branch information for comparison
        # To check if PR is behind base, we need to compare the branches (not SHAs)
        # Using branch refs ensures we compare the current state of the branches
        base_branch = pr_data['base']['ref']
        head_branch = pr_data['head']['ref']
        # For forks, we need to use the full ref format
        # Handle case where fork is deleted (repo is None)
        head_repo = pr_data['head'].get('repo')
        if head_repo and head_repo.get('owner'):
            head_full_ref = f"{head_repo['owner']['login']}:{head_branch}"
        else:
            # If fork is deleted, use just the branch name (comparison will likely fail but won't crash)
            print(f"Warning: PR #{pr_number} head repository is None (fork may be deleted)")
            head_full_ref = head_branch
        
        # Compare head...base to see how many commits base has that head doesn't
        compare_url = f"https://api.github.com/repos/{owner}/{repo}/compare/{head_full_ref}...{base_branch}"
        
        # Fetch checks, comparison, reviews, and conversations in parallel using asyncio.gather
        # This reduces total fetch time from sequential sum to max single request time
        # Files list is excluded since we only need the count which is in pr_data['changed_files']
        checks_data = {}
        compare_data = {}
        reviews_data = []
        open_conversations_count = 0
        
        try:
            results = await asyncio.gather(
                fetch_with_headers(checks_url, secondary_headers, token),
                fetch_with_headers(compare_url, secondary_headers, token),
                fetch_open_conversations_count(owner, repo, pr_number, token),
                fetch_with_headers(reviews_url, secondary_headers, token),
                return_exceptions=True
            )
            
            # Process checks result
            if not isinstance(results[0], Exception) and results[0].status == 200:
                checks_data = (await results[0].json()).to_py()
            
            # Process compare result
            if not isinstance(results[1], Exception) and results[1].status == 200:
                compare_data = (await results[1].json()).to_py()
                print(f"Compare API success for PR #{pr_number}")
            elif not isinstance(results[1], Exception):
                # Log error if compare API fails
                print(f"Compare API failed for PR #{pr_number} with status {results[1].status}, URL: {compare_url}")
            else:
                print(f"Compare API exception for PR #{pr_number}: {results[1]}")
            
            # Process open conversations count result
            if not isinstance(results[2], Exception):
                open_conversations_count = results[2]
            else:
                print(f"Open conversations fetch exception for PR #{pr_number}: {results[2]}")
            
            # Process reviews result
            if not isinstance(results[3], Exception) and results[3].status == 200:
                reviews_data = (await results[3].json()).to_py()
            else:
                print(f"Reviews fetch failed for PR #{pr_number}")
        except Exception as e:
            print(f"Error fetching PR data for #{pr_number}: {str(e)}")
        
        # Process check runs
        checks_passed = 0
        checks_failed = 0
        checks_skipped = 0
        
        if 'check_runs' in checks_data:
            for check in checks_data['check_runs']:
                if check['conclusion'] == 'success':
                    checks_passed += 1
                elif check['conclusion'] in ['failure', 'timed_out', 'cancelled']:
                    checks_failed += 1
                elif check['conclusion'] in ['skipped', 'neutral']:
                    checks_skipped += 1
        
        # Get commits count from pr_data (GitHub provides this)
        commits_count = pr_data.get('commits', 0)
        
        # Get behind_by count from compare data
        # When comparing head...base, ahead_by tells us how many commits base has that head doesn't
        behind_by = 0
        if compare_data:
            # Use ahead_by since we reversed the comparison (head...base)
            # Use 'or 0' to handle None values from GitHub API
            behind_by = compare_data.get('ahead_by') or 0
            print(f"PR #{pr_number}: Compare status={compare_data.get('status')}, ahead_by={compare_data.get('ahead_by')}, behind_by={compare_data.get('behind_by')}")
        
        # Calculate review status from reviews data
        from utils import calculate_review_status
        review_status = calculate_review_status(reviews_data)
        
        # Build per-reviewer data for the Approvals column - Keep only the latest review state per reviewer
        latest_reviews = {}
        if reviews_data:
            valid_reviews = [r for r in reviews_data if r.get('submitted_at') and r.get('user')]
            sorted_reviews = sorted(valid_reviews, key=lambda x: x.get('submitted_at', ''))
            for review in sorted_reviews:
                user = review['user']
                latest_reviews[user['login']] = {
                    'login': user['login'],
                    'avatar_url': user.get('avatar_url', ''),
                    'state': review['state']  # APPROVED, CHANGES_REQUESTED, COMMENTED, etc.
                }
        reviewers_list = list(latest_reviews.values())
        
        # Safely access user fields - user can be null for deleted accounts
        user = pr_data.get('user') or {}
        
        return {
            'title': pr_data.get('title', ''),
            'state': pr_data.get('state', ''),
            'is_merged': 1 if pr_data.get('merged', False) else 0,
            'repo_private': bool(pr_data.get('base', {}).get('repo', {}).get('private', False)),
            'mergeable_state': pr_data.get('mergeable_state', ''),
            'files_changed': pr_data.get('changed_files', 0),  # Use changed_files from PR data instead of fetching files list
            'author_login': user.get('login', 'ghost'),
            'author_avatar': user.get('avatar_url', ''),
            'repo_owner_avatar': pr_data.get('base', {}).get('repo', {}).get('owner', {}).get('avatar_url', ''),
            'checks_passed': checks_passed,
            'checks_failed': checks_failed,
            'checks_skipped': checks_skipped,
            'commits_count': commits_count,
            'behind_by': behind_by,
            'review_status': review_status,
            'last_updated_at': pr_data.get('updated_at', ''),
            'is_draft': 1 if pr_data.get('draft', False) else 0,
            'open_conversations_count': open_conversations_count,
            'reviewers_json': json.dumps(reviewers_list),
            'etag': new_etag
        }
    except Exception as e:
        # Return more informative error for debugging
        error_msg = f"Error fetching PR data: {str(e)}"
        # In Cloudflare Workers, console.error is preferred
        raise Exception(error_msg)


async def fetch_multiple_prs_batch(prs_to_fetch, token=None):
    """
    Fetch multiple PR data efficiently using GitHub GraphQL API in a single call.
    
    This significantly reduces API calls when updating many PRs at once.
    Instead of making 4-5 REST API calls per PR, we make 1 GraphQL call for all PRs.
    
    IMPORTANT TRADEOFFS:
    - Does not fetch check run status (checks_passed/failed/skipped) - set to 0
    - Does not fetch behind_by count - set to 0
    - No ETag support for conditional requests
    - Limited to first 100 review threads per PR
    - Best for bulk updates where these fields are less critical
    - For complete/accurate data, use individual fetch_pr_data() instead
    
    Args:
        prs_to_fetch: List of tuples (owner, repo, pr_number) to fetch
        token: Optional GitHub token for authentication
        
    Returns:
        dict: Mapping of (owner, repo, pr_number) -> pr_data or None on error
    """
    if not prs_to_fetch:
        return {}
    
    # GraphQL has limits, so we batch in groups of 50 PRs max
    MAX_PRS_PER_BATCH = 50
    graphql_url = "https://api.github.com/graphql"
    all_results = {}

    def _escape_graphql_string(value):
        """Escape a Python string for safe GraphQL string literal embedding."""
        if value is None:
            return ''
        return str(value).replace('\\', '\\\\').replace('"', '\\"')

    def _normalize_ref_name(ref_name):
        """Convert branch names like 'main' to GraphQL qualified refs."""
        ref_name = (ref_name or '').strip()
        if not ref_name:
            return ''
        if ref_name.startswith('refs/'):
            return ref_name
        return f"refs/heads/{ref_name}"
    
    # Process in batches
    for batch_start in range(0, len(prs_to_fetch), MAX_PRS_PER_BATCH):
        batch = prs_to_fetch[batch_start:batch_start + MAX_PRS_PER_BATCH]
        
        # Build GraphQL query with aliases for each PR
        # Pass 1 fetches essential PR data + head/base refs for pass 2 comparison query.
        query_parts = []
        for i, (owner, repo, pr_number) in enumerate(batch):
            alias = f"pr{i}"
            query_parts.append(f"""
                {alias}: repository(owner: "{_escape_graphql_string(owner)}", name: "{_escape_graphql_string(repo)}") {{
                    pullRequest(number: {pr_number}) {{
                        title
                        state
                        isDraft
                        merged
                        updatedAt
                        mergeable
                        mergeStateStatus
                        changedFiles
                        commits(last: 1) {{
                            totalCount
                            nodes {{
                                commit {{
                                    statusCheckRollup {{
                                        contexts(first: 100) {{
                                            nodes {{
                                                __typename
                                                ... on CheckRun {{
                                                    conclusion
                                                    status
                                                }}
                                                ... on StatusContext {{
                                                    state
                                                }}
                                            }}
                                        }}
                                    }}
                                }}
                            }}
                        }}
                        author {{
                            login
                            avatarUrl
                        }}
                        baseRepository {{
                            owner {{
                                avatarUrl
                            }}
                        }}
                        headRefOid
                        baseRefName
                        headRefName
                        headRepository {{
                            owner {{
                                login
                            }}
                        }}
                        reviewThreads(first: 100) {{
                            nodes {{
                                isResolved
                            }}
                            pageInfo {{
                                hasNextPage
                            }}
                        }}
                        reviews(first: 100) {{
                            nodes {{
                                state
                                submittedAt
                                author {{
                                    login
                                    avatarUrl
                                }}
                            }}
                        }}
                    }}
                }}
            """)
        
        query = "query { " + " ".join(query_parts) + " }"
        
        headers = {
            'Accept': 'application/vnd.github+json',
            'Content-Type': 'application/json',
            'User-Agent': 'PR-Tracker/1.0'
        }
        
        if token:
            headers['Authorization'] = f'Bearer {token}'
        
        try:
            # Make GraphQL request
            options = to_js({
                "method": "POST",
                "headers": headers,
                "body": json.dumps({"query": query})
            }, dict_converter=Object.fromEntries)
            
            response = await fetch(graphql_url, options)
            
            # Log GraphQL API call
            rate_limit = response.headers.get('x-ratelimit-limit')
            rate_remaining = response.headers.get('x-ratelimit-remaining')
            rate_reset = response.headers.get('x-ratelimit-reset')
            if rate_limit and rate_remaining:
                set_rate_limit_data(rate_limit, rate_remaining, rate_reset)
                
            print(f"GitHub GraphQL Batch API: Fetched {len(batch)} PRs | Status: {response.status} | Rate Limit: {rate_remaining}/{rate_limit} remaining")
            
            if response.status != 200:
                print(f"Warning: GraphQL Batch API returned status {response.status}")
                # Mark all PRs in this batch as failed
                for owner, repo, pr_number in batch:
                    all_results[(owner, repo, pr_number)] = None
                continue
            
            result = (await response.json()).to_py()
            
            # Check for GraphQL errors
            if 'errors' in result:
                print(f"GraphQL Batch errors: {result['errors']}")
                # Mark all PRs in this batch as failed
                for owner, repo, pr_number in batch:
                    all_results[(owner, repo, pr_number)] = None
                continue
            
            # Extract PR data from response
            data = result.get('data', {})
            # Save comparison targets for a pass-2 GraphQL compare query
            comparison_targets = {}
            for i, (owner, repo, pr_number) in enumerate(batch):
                alias = f"pr{i}"
                repo_data = data.get(alias, {})
                pr_data = repo_data.get('pullRequest') if repo_data else None
                
                if not pr_data:
                    print(f"Warning: No PR data in GraphQL response for {owner}/{repo}#{pr_number}")
                    all_results[(owner, repo, pr_number)] = None
                    continue

                comparison_targets[(owner, repo, pr_number)] = {
                    'base_ref': pr_data.get('baseRefName'),
                    'head_oid': pr_data.get('headRefOid')
                }

            # Pass 2: Batch compare all PRs from this chunk to compute accurate behind_by
            comparison_query_parts = []
            compare_keys = list(comparison_targets.keys())
            for i, key in enumerate(compare_keys):
                owner, repo, pr_number = key
                compare_alias = f"cmp{i}"
                base_ref = _normalize_ref_name(comparison_targets[key].get('base_ref'))
                head_oid = comparison_targets[key].get('head_oid')

                if not base_ref or not head_oid:
                    continue

                comparison_query_parts.append(f"""
                    {compare_alias}: repository(owner: "{_escape_graphql_string(owner)}", name: "{_escape_graphql_string(repo)}") {{
                        baseRef: ref(qualifiedName: "{_escape_graphql_string(base_ref)}") {{
                            compare(headRef: "{_escape_graphql_string(head_oid)}") {{
                                aheadBy
                                behindBy
                            }}
                        }}
                    }}
                """)

            behind_by_map = {}
            if comparison_query_parts:
                comparison_query = "query { " + " ".join(comparison_query_parts) + " }"
                comparison_options = to_js({
                    "method": "POST",
                    "headers": headers,
                    "body": json.dumps({"query": comparison_query})
                }, dict_converter=Object.fromEntries)

                comparison_response = await fetch(graphql_url, comparison_options)
                if comparison_response.status == 200:
                    comparison_result = (await comparison_response.json()).to_py()
                    if 'errors' in comparison_result:
                        print(f"GraphQL compare errors: {comparison_result['errors']}")
                    else:
                        comparison_data = comparison_result.get('data', {})
                        for i, key in enumerate(compare_keys):
                            alias = f"cmp{i}"
                            repo_compare = comparison_data.get(alias, {})
                            ref_data = repo_compare.get('baseRef') if repo_compare else None
                            compare_data = ref_data.get('compare') if ref_data else None
                            if compare_data:
                                # Prefer behindBy. Fallback to aheadBy if behindBy is missing.
                                behind_by = compare_data.get('behindBy')
                                if behind_by is None:
                                    behind_by = compare_data.get('aheadBy')
                                behind_by_map[key] = int(behind_by or 0)
                            else:
                                behind_by_map[key] = 0
                else:
                    print(f"Warning: GraphQL compare query returned status {comparison_response.status}")
                    for key in compare_keys:
                        behind_by_map[key] = 0
                
                # Transform GraphQL response to match REST API format used by fetch_pr_data
                author = pr_data.get('author', {})
                base_repo = pr_data.get('baseRepository', {})
                
                # Count unresolved conversations
                review_threads = pr_data.get('reviewThreads', {}).get('nodes', [])
                open_conversations_count = sum(1 for thread in review_threads if not thread.get('isResolved', False))
                
                # Note: If there are more than 100 review threads, this count will be incomplete
                # The pageInfo would indicate hasNextPage=true in that case
                page_info = pr_data.get('reviewThreads', {}).get('pageInfo', {})
                if page_info.get('hasNextPage'):
                    print(f"Warning: PR {owner}/{repo}#{pr_number} has >100 review threads, count may be incomplete")
                
                # Process reviews to get latest state per reviewer
                from utils import calculate_review_status
                reviews_data = pr_data.get('reviews', {}).get('nodes', [])
                review_status = calculate_review_status(reviews_data)
                
                # Build per-reviewer data
                latest_reviews = {}
                if reviews_data:
                    valid_reviews = [r for r in reviews_data if r.get('submittedAt') and r.get('author')]
                    sorted_reviews = sorted(valid_reviews, key=lambda x: x.get('submittedAt', ''))
                    for review in sorted_reviews:
                        author_data = review['author']
                        latest_reviews[author_data['login']] = {
                            'login': author_data['login'],
                            'avatar_url': author_data.get('avatarUrl', ''),
                            'state': review['state']
                        }
                reviewers_list = list(latest_reviews.values())

                # Count CI check results from statusCheckRollup on the latest commit
                checks_passed = 0
                checks_failed = 0
                checks_skipped = 0
                last_commit_nodes = pr_data.get('commits', {}).get('nodes', [])
                if last_commit_nodes:
                    rollup = (last_commit_nodes[0].get('commit') or {}).get('statusCheckRollup') or {}
                    for ctx in rollup.get('contexts', {}).get('nodes', []):
                        typename = ctx.get('__typename', '')
                        if typename == 'CheckRun':
                            conclusion = (ctx.get('conclusion') or '').upper()
                            if conclusion == 'SUCCESS':
                                checks_passed += 1
                            elif conclusion in ('FAILURE', 'TIMED_OUT', 'CANCELLED'):
                                checks_failed += 1
                            elif conclusion in ('SKIPPED', 'NEUTRAL'):
                                checks_skipped += 1
                        elif typename == 'StatusContext':
                            state = (ctx.get('state') or '').upper()
                            if state == 'SUCCESS':
                                checks_passed += 1
                            elif state in ('FAILURE', 'ERROR'):
                                checks_failed += 1
                
                # Build the pr_data dict matching REST API format
                transformed_data = {
                    'title': pr_data.get('title', ''),
                    'state': pr_data.get('state', '').lower(),
                    'is_merged': 1 if pr_data.get('merged', False) else 0,
                    'mergeable_state': pr_data.get('mergeStateStatus', 'unknown'),
                    'files_changed': pr_data.get('changedFiles', 0),
                    'author_login': author.get('login', ''),
                    'author_avatar': author.get('avatarUrl', ''),
                    'repo_owner_avatar': base_repo.get('owner', {}).get('avatarUrl', ''),
                    'checks_passed': checks_passed,
                    'checks_failed': checks_failed,
                    'checks_skipped': checks_skipped,
                    'commits_count': pr_data.get('commits', {}).get('totalCount', 0),
                    'behind_by': behind_by_map.get((owner, repo, pr_number), 0),
                    'review_status': review_status,
                    'last_updated_at': pr_data.get('updatedAt', ''),
                    'is_draft': 1 if pr_data.get('isDraft', False) else 0,
                    'open_conversations_count': open_conversations_count,
                    'reviewers_json': json.dumps(reviewers_list),
                    'etag': None,  # GraphQL doesn't provide ETags
                    '_batch_fetch': True
                }
                
                all_results[(owner, repo, pr_number)] = transformed_data
                
        except Exception as e:
            print(f"Error in GraphQL batch fetch: {str(e)}")
            # Mark all PRs in this batch as failed
            for owner, repo, pr_number in batch:
                all_results[(owner, repo, pr_number)] = None
    
    return all_results


async def fetch_org_repos(owner, token=None, max_repos=200):
    """
    Fetch all public repositories for a GitHub organization or user.
    
    Tries the /orgs/ endpoint first; if the owner is a user (not an org),
    falls back to the /users/ endpoint. If authentication fails (401),
    retries without the token since public repos don't require auth.
    
    Args:
        owner: GitHub org or user name
        token: Optional GitHub token for authentication
        max_repos: Maximum number of repos to return (default 200)
    
    Returns:
        List of repository dicts with 'name' and 'owner' keys, or raises Exception.
    """
    headers_dict = {
        'User-Agent': 'PR-Tracker/1.0',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28'
    }
    
    # Try org endpoint first, then fall back to user endpoint
    org_url = f"https://api.github.com/orgs/{owner}/repos?type=public&sort=updated&direction=desc&per_page=100"
    user_url = f"https://api.github.com/users/{owner}/repos?type=public&sort=updated&direction=desc&per_page=100"
    
    # Trying without token first to preserve token rate limit (public repos don't need auth).
    # If we get 401/403 (private org requiring auth) - retry with token.
    tokens_to_try = [None, token] if token else [None]
    
    for current_token in tokens_to_try:
        for url in [org_url, user_url]:
            try:
                result = await fetch_paginated_data(
                    url, headers_dict, github_token=current_token,
                    max_items=max_repos, return_metadata=True
                )
                repos = result['items']
                if repos is not None:
                    # Filter to non-fork, non-archived repos and extract name + owner
                    filtered = []
                    for r in repos:
                        if r.get('archived'):
                            continue
                        filtered.append({
                            'name': r['name'],
                            'owner': r.get('owner', {}).get('login', owner),
                            'open_issues_count': r.get('open_issues_count', 0),
                            'has_issues': r.get('has_issues', True)
                        })
                    return filtered
            except Exception as e:
                error_msg = str(e)
                # 404 means this endpoint type is wrong (org vs user), try next URL
                if 'status=404' in error_msg:
                    continue
                # 401/403 means auth needed (e.g. private org) - break inner loop to retry with token
                if 'status=401' in error_msg or 'status=403' in error_msg:
                    print(f"GitHub API returned auth error for {url} - will retry with token")
                    break
                raise
    
    raise Exception(f"Could not find GitHub organization or user: {owner}")


async def fetch_repo_open_pr_numbers(owner, repo, token=None):
    """
    Fetch the PR numbers of all currently open PRs in a repository. Makes a single paginated REST call.
    Used by the repository-level phase of the scheduled refresh to detect
    newly-opened PRs and PRs that have been closed/merged since the last run.
    """
    headers_dict = {
        'User-Agent': 'PR-Tracker/1.0',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28'
    }
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls?state=open&per_page=100"
    prs = await fetch_paginated_data(url, headers_dict, github_token=token)
    return {pr['number'] for pr in prs}


async def fetch_repo_open_prs(owner, repo, token=None, include_metadata=False):
    """
    Fetch all open PRs for a repository via GraphQL with pagination.

    Returns a list of dictionaries with fields required for repo-level refresh,
    including head/base refs needed to compute behind_by in batch.

    When include_metadata=True, returns:
        {
            'prs': [...],
            'repo_is_private': bool
        }
    """
    graphql_url = "https://api.github.com/graphql"
    headers = {
        'Accept': 'application/vnd.github+json',
        'Content-Type': 'application/json',
        'User-Agent': 'PR-Tracker/1.0'
    }
    if token:
        headers['Authorization'] = f'Bearer {token}'

    query = """
    query($owner: String!, $repo: String!, $cursor: String) {
      repository(owner: $owner, name: $repo) {
                isPrivate
        pullRequests(states: OPEN, first: 100, after: $cursor, orderBy: {field: UPDATED_AT, direction: DESC}) {
          nodes {
            number
            title
            updatedAt
            isDraft
            headRefOid
            baseRefName
            author {
              login
              avatarUrl
            }
            baseRepository {
              owner {
                avatarUrl
              }
            }
          }
          pageInfo {
            hasNextPage
            endCursor
          }
        }
      }
    }
    """

    all_nodes = []
    repo_is_private = False
    cursor = None
    has_next_page = True

    while has_next_page:
        options = to_js({
            "method": "POST",
            "headers": headers,
            "body": json.dumps({
                "query": query,
                "variables": {
                    "owner": owner,
                    "repo": repo,
                    "cursor": cursor
                }
            })
        }, dict_converter=Object.fromEntries)

        response = await fetch(graphql_url, options)

        rate_limit = response.headers.get('x-ratelimit-limit')
        rate_remaining = response.headers.get('x-ratelimit-remaining')
        rate_reset = response.headers.get('x-ratelimit-reset')
        if rate_limit and rate_remaining:
            set_rate_limit_data(rate_limit, rate_remaining, rate_reset)

        if response.status != 200:
            raise Exception(f"GraphQL open PR query failed: status={response.status}")

        result = (await response.json()).to_py()
        if 'errors' in result:
            raise Exception(f"GraphQL open PR query errors: {result['errors']}")

        repository_data = result.get('data', {}).get('repository')
        if not repository_data:
            raise Exception(f"GraphQL open PR query returned no repository for {owner}/{repo}")

        repo_is_private = bool(repository_data.get('isPrivate', False))
        pr_data = repository_data.get('pullRequests', {})
        nodes = pr_data.get('nodes', [])
        page_info = pr_data.get('pageInfo', {})

        all_nodes.extend(nodes)
        has_next_page = bool(page_info.get('hasNextPage'))
        cursor = page_info.get('endCursor')

    if include_metadata:
        return {
            'prs': all_nodes,
            'repo_is_private': repo_is_private,
        }

    return all_nodes


async def fetch_repo_comparison_batch(owner, repo, repo_open_prs, token=None):
    """
    Compute behind_by for many PRs in one repository using GraphQL compare.
    
    Returns a mapping of pr_number -> behind_by count for all PRs in repo_open_prs.
    """
    if not repo_open_prs:
        return {}

    graphql_url = "https://api.github.com/graphql"
    headers = {
        'Accept': 'application/vnd.github+json',
        'Content-Type': 'application/json',
        'User-Agent': 'PR-Tracker/1.0'
    }
    if token:
        headers['Authorization'] = f'Bearer {token}'

    def _escape_graphql_string(value):
        if value is None:
            return ''
        return str(value).replace('\\', '\\\\').replace('"', '\\"')

    def _normalize_ref_name(ref_name):
        ref_name = (ref_name or '').strip()
        if not ref_name:
            return ''
        if ref_name.startswith('refs/'):
            return ref_name
        return f"refs/heads/{ref_name}"

    behind_by_map = {}

    MAX_COMPARE_PER_QUERY = 100
    for start in range(0, len(repo_open_prs), MAX_COMPARE_PER_QUERY):
        chunk = repo_open_prs[start:start + MAX_COMPARE_PER_QUERY]

        query_parts = []
        index_to_pr_number = {}

        for i, pr in enumerate(chunk):
            pr_number = pr.get('number')
            base_ref = _normalize_ref_name(pr.get('baseRefName'))
            head_oid = pr.get('headRefOid')

            if not pr_number or not base_ref or not head_oid:
                if pr_number:
                    behind_by_map[pr_number] = 0
                continue

            alias = f"cmp{i}"
            index_to_pr_number[i] = pr_number
            query_parts.append(f"""
                {alias}: ref(qualifiedName: "{_escape_graphql_string(base_ref)}") {{
                    compare(headRef: "{_escape_graphql_string(head_oid)}") {{
                        aheadBy
                        behindBy
                    }}
                }}
            """)

        if not query_parts:
            continue

        query = f"""
        query {{
          repository(owner: "{_escape_graphql_string(owner)}", name: "{_escape_graphql_string(repo)}") {{
            {' '.join(query_parts)}
          }}
        }}
        """

        options = to_js({
            "method": "POST",
            "headers": headers,
            "body": json.dumps({"query": query})
        }, dict_converter=Object.fromEntries)

        response = await fetch(graphql_url, options)

        rate_limit = response.headers.get('x-ratelimit-limit')
        rate_remaining = response.headers.get('x-ratelimit-remaining')
        rate_reset = response.headers.get('x-ratelimit-reset')
        if rate_limit and rate_remaining:
            set_rate_limit_data(rate_limit, rate_remaining, rate_reset)

        if response.status != 200:
            raise Exception(f"GraphQL comparison batch failed: status={response.status}")

        result = (await response.json()).to_py()
        
        if 'errors' in result:
            print(f"GraphQL comparison batch errors: {result['errors']}")

        repo_data = (result.get('data') or {}).get('repository') or {}
        for i, pr_number in index_to_pr_number.items():
            alias = f"cmp{i}"
            ref_data = repo_data.get(alias, {})
            compare_data = ref_data.get('compare') if ref_data else None
            if compare_data:
                behind_by = compare_data.get('behindBy')
                if behind_by is None:
                    behind_by = compare_data.get('aheadBy')
                behind_by_map[pr_number] = int(behind_by or 0)
            else:
                behind_by_map[pr_number] = 0

    return behind_by_map


async def fetch_paginated_data(url, headers_dict, github_token=None, max_items=None, return_metadata=False):
    """
    Fetch all pages of data from a GitHub API endpoint following Link headers
    
    Args:
        url: Initial URL to fetch
        headers: Headers object to use for requests
        max_items: Optional maximum number of items to fetch (default: unlimited).
                  Must be None or a positive integer.
        return_metadata: If True, returns dict with items, truncated, and total_fetched.
                        If False (default), returns just the list of items for backward compatibility.
    
    Returns:
        If return_metadata=False: List of all items fetched
        If return_metadata=True: Dictionary with:
            - items: List of all items fetched
            - truncated: Boolean indicating if results were truncated due to max_items limit
            - total_fetched: Total number of items fetched
    """
    # Validate max_items parameter
    if max_items is not None and (not isinstance(max_items, int) or max_items <= 0):
        raise ValueError(f"max_items must be None or a positive integer, got: {max_items}")
    
    all_data = []
    current_url = url
    truncated = False
    
    while current_url:
        response = await fetch_with_headers(current_url, headers_dict, github_token)
        
        # Log GitHub API call with rate limit information
        # Check if URL starts with GitHub API domain for logging purposes only
        if current_url.startswith('https://api.github.com/'):
            rate_limit = response.headers.get('x-ratelimit-limit')
            rate_remaining = response.headers.get('x-ratelimit-remaining')
            rate_reset = response.headers.get('x-ratelimit-reset')
            print(f"GitHub API: {current_url} | Status: {response.status} | Rate Limit: {rate_remaining}/{rate_limit} remaining | Reset: {rate_reset}")
        
        if not response.ok:
            status = getattr(response, 'status', 'unknown')
            status_text = getattr(response, 'statusText', '')
            raise Exception(
                f"GitHub API error: status={status} {status_text} url={current_url}"
            )
        
        page_data = (await response.json()).to_py()
        
        # Break early if we receive an empty page (end of results)
        if not page_data:
            break
        
        # Check for Link header to get next page (needed for truncation logic)
        link_header = response.headers.get('link')
        has_next_page = False
        if link_header:
            links = link_header.split(',')
            for link in links:
                if 'rel="next"' in link:
                    has_next_page = True
                    break
        
        # Check if adding this page would exceed max_items
        if max_items is not None:
            items_to_add = min(len(page_data), max_items - len(all_data))
            all_data.extend(page_data[:items_to_add])
            
            if len(all_data) >= max_items:
                # Only mark as truncated if there's actually more data available
                if has_next_page or items_to_add < len(page_data):
                    truncated = True
                print(f"Pagination limit reached: {len(all_data)} items (max: {max_items})")
                break
        else:
            all_data.extend(page_data)
        
        # Determine URL for next page, if any
        current_url = None
        if has_next_page:
            # Extract URL from <url>
            for link in links:
                if 'rel="next"' in link:
                    url_match = link.split(';')[0].strip()
                    if url_match.startswith('<') and url_match.endswith('>'):
                        current_url = url_match[1:-1]
                    break
    
    if return_metadata:
        return {
            'items': all_data,
            'truncated': truncated,
            'total_fetched': len(all_data)
        }
    else:
        return all_data


async def fetch_pr_timeline_data(env, owner, repo, pr_number, github_token=None):
    """
    Fetch all timeline data for a PR: commits, reviews, review comments, issue comments
    
    Uses in-memory caching (30 min TTL) with D1 fallback to avoid redundant API calls.
    All 4 API calls are made in parallel for optimal performance.
    
    Note: Reviews are fetched here (not in fetch_pr_data) to avoid duplication.
    
    Returns dict with raw data from GitHub API:
    {
        'commits': [...],
        'reviews': [...],
        'review_comments': [...],
        'issue_comments': [...]
    }
    """
    # Check cache first (async)
    cached_data = await get_timeline_cache(env, owner, repo, pr_number)
    if cached_data:
        return cached_data
    
    base_url = 'https://api.github.com'
    
    # Prepare headers
    headers_dict = {
        'User-Agent': 'PR-Tracker/1.0',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28'
    }
    if github_token:
        headers_dict['Authorization'] = f'Bearer {github_token}'
    
    
    try:
        # Fetch all timeline data in parallel (with pagination)
        commits_url = f'{base_url}/repos/{owner}/{repo}/pulls/{pr_number}/commits?per_page=100'
        reviews_url = f'{base_url}/repos/{owner}/{repo}/pulls/{pr_number}/reviews?per_page=100'
        review_comments_url = f'{base_url}/repos/{owner}/{repo}/pulls/{pr_number}/comments?per_page=100'
        issue_comments_url = f'{base_url}/repos/{owner}/{repo}/issues/{pr_number}/comments?per_page=100'
        
        # Make truly parallel requests using asyncio.gather
        commits_data, reviews_data, review_comments_data, issue_comments_data = await asyncio.gather(
            fetch_paginated_data(commits_url, headers_dict, github_token),
            fetch_paginated_data(reviews_url, headers_dict, github_token),
            fetch_paginated_data(review_comments_url, headers_dict, github_token),
            fetch_paginated_data(issue_comments_url, headers_dict, github_token)
        )
        
        timeline_data = {
            'commits': commits_data,
            'reviews': reviews_data,
            'review_comments': review_comments_data,
            'issue_comments': issue_comments_data
        }
        
        # Cache the result for future requests (async)
        await set_timeline_cache(env, owner, repo, pr_number, timeline_data)
        
        return timeline_data
    except Exception as e:
        raise Exception(f"Error fetching timeline data: {str(e)}")


async def verify_github_signature(request, payload_body, secret):
    """
    Verify GitHub webhook signature.
    
    Args:
        request: The request object containing headers
        payload_body: Raw request body as bytes or string
        secret: Webhook secret configured in GitHub
        
    Returns:
        bool: True if signature is valid, False otherwise
    """
    if not secret:
        # If no secret is configured, skip verification (development mode)
        print("WARNING: Webhook secret not configured - skipping signature verification")
        return True
    
    signature_header = request.headers.get('x-hub-signature-256')
    if not signature_header:
        return False
    
    # GitHub sends signature as "sha256=<hash>"
    try:
        import hashlib
        import hmac
        
        # Ensure payload_body is bytes
        if isinstance(payload_body, str):
            payload_body = payload_body.encode('utf-8')
        
        # Calculate expected signature
        hash_object = hmac.new(secret.encode('utf-8'), msg=payload_body, digestmod=hashlib.sha256)
        expected_signature = "sha256=" + hash_object.hexdigest()
        
        # Constant-time comparison to prevent timing attacks
        return hmac.compare_digest(expected_signature, signature_header)
    except Exception as e:
        print(f"Error verifying webhook signature: {e}")
        return False
