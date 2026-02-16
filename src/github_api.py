"""
GitHub API interaction functions
"""
from js import fetch, Headers, Object
from pyodide.ffi import to_js
import asyncio

from cache import get_timeline_cache, set_timeline_cache
from utils import parse_github_timestamp


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
    return await fetch(url, options)


async def fetch_pr_data(owner, repo, pr_number, token=None):
    """Fetch PR data from GitHub API with parallel requests for optimal performance"""
    headers = {
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28'
    }
        
    try:
        # Fetch PR details first (needed for head SHA)
        pr_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
        pr_response = await fetch_with_headers(pr_url, headers, token)
        
        if pr_response.status != 200:
            return None
            
        pr_data = (await pr_response.json()).to_py()

        # Prepare URLs for parallel fetching
        files_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files"
        reviews_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
        checks_url = f"https://api.github.com/repos/{owner}/{repo}/commits/{pr_data['head']['sha']}/check-runs"
        
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
        
        # Fetch files, reviews, checks, and comparison in parallel using asyncio.gather
        # This reduces total fetch time from sequential sum to max single request time
        files_data = []
        reviews_data = []
        checks_data = {}
        compare_data = {}
        
        try:
            results = await asyncio.gather(
                fetch_with_headers(files_url, headers, token),
                fetch_with_headers(reviews_url, headers, token),
                fetch_with_headers(checks_url, headers, token),
                fetch_with_headers(compare_url, headers, token),
                return_exceptions=True
            )
            
            # Process files result
            if not isinstance(results[0], Exception) and results[0].status == 200:
                files_data = (await results[0].json()).to_py()
            
            # Process reviews result
            if not isinstance(results[1], Exception) and results[1].status == 200:
                reviews_data = (await results[1].json()).to_py()
            
            # Process checks result
            if not isinstance(results[2], Exception) and results[2].status == 200:
                checks_data = (await results[2].json()).to_py()
            
            # Process compare result
            if not isinstance(results[3], Exception) and results[3].status == 200:
                compare_data = (await results[3].json()).to_py()
                print(f"Compare API success for PR #{pr_number}")
            elif not isinstance(results[3], Exception):
                # Log error if compare API fails
                print(f"Compare API failed for PR #{pr_number} with status {results[3].status}, URL: {compare_url}")
            else:
                print(f"Compare API exception for PR #{pr_number}: {results[3]}")
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
        
        # Determine review status - sort by submitted_at to get latest reviews
        review_status = 'pending'
        if reviews_data:
            # Sort reviews by submitted_at to get chronological order
            sorted_reviews = sorted(reviews_data, key=lambda x: x.get('submitted_at', ''))
            latest_reviews = {}
            for review in sorted_reviews:
                user = review['user']['login']
                latest_reviews[user] = review['state']

            # Determine overall status: changes_requested takes precedence over approved
            if 'CHANGES_REQUESTED' in latest_reviews.values():
                review_status = 'changes_requested'
            elif 'APPROVED' in latest_reviews.values():
                review_status = 'approved'
        
        return {
            'title': pr_data.get('title', ''),
            'state': pr_data.get('state', ''),
            'is_merged': 1 if pr_data.get('merged', False) else 0,
            'mergeable_state': pr_data.get('mergeable_state', ''),
            'files_changed': len(files_data), 
            'author_login': pr_data['user']['login'],
            'author_avatar': pr_data['user']['avatar_url'],
            'repo_owner_avatar': pr_data.get('base', {}).get('repo', {}).get('owner', {}).get('avatar_url', ''),
            'checks_passed': checks_passed,
            'checks_failed': checks_failed,
            'checks_skipped': checks_skipped,
            'commits_count': commits_count,
            'behind_by': behind_by,
            'review_status': review_status,
            'last_updated_at': pr_data.get('updated_at', ''),
            'is_draft': 1 if pr_data.get('draft', False) else 0
        }
    except Exception as e:
        # Return more informative error for debugging
        error_msg = f"Error fetching PR data: {str(e)}"
        # In Cloudflare Workers, console.error is preferred
        raise Exception(error_msg)


async def fetch_paginated_data(url, headers):
    """
    Fetch all pages of data from a GitHub API endpoint following Link headers
    
    Args:
        url: Initial URL to fetch
        headers: Headers object to use for requests
    
    Returns:
        List of all items across all pages
    """
    all_data = []
    current_url = url
    fetch_options = to_js({'headers': headers}, dict_converter=Object.fromEntries)
    
    while current_url:
        response = await fetch(current_url, fetch_options)
        
        if not response.ok:
            status = getattr(response, 'status', 'unknown')
            status_text = getattr(response, 'statusText', '')
            raise Exception(
                f"GitHub API error: status={status} {status_text} url={current_url}"
            )
        
        page_data = (await response.json()).to_py()
        all_data.extend(page_data)
        
        # Check for Link header to get next page
        link_header = response.headers.get('link')
        current_url = None
        
        if link_header:
            # Parse Link header: <url>; rel="next", <url>; rel="last"
            links = link_header.split(',')
            for link in links:
                if 'rel="next"' in link:
                    # Extract URL from <url>
                    url_match = link.split(';')[0].strip()
                    if url_match.startswith('<') and url_match.endswith('>'):
                        current_url = url_match[1:-1]
                    break
    
    return all_data


async def fetch_pr_timeline_data(owner, repo, pr_number, github_token=None):
    """
    Fetch all timeline data for a PR: commits, reviews, review comments, issue comments
    
    Uses in-memory caching (30 min TTL) to avoid redundant API calls across endpoints.
    
    Returns dict with raw data from GitHub API:
    {
        'commits': [...],
        'reviews': [...],
        'review_comments': [...],
        'issue_comments': [...]
    }
    """
    # Check cache first
    cached_data = get_timeline_cache(owner, repo, pr_number)
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
    
    headers = Headers.new(to_js(headers_dict, dict_converter=Object.fromEntries))
    
    try:
        # Fetch all timeline data in parallel (with pagination)
        commits_url = f'{base_url}/repos/{owner}/{repo}/pulls/{pr_number}/commits?per_page=100'
        reviews_url = f'{base_url}/repos/{owner}/{repo}/pulls/{pr_number}/reviews?per_page=100'
        review_comments_url = f'{base_url}/repos/{owner}/{repo}/pulls/{pr_number}/comments?per_page=100'
        issue_comments_url = f'{base_url}/repos/{owner}/{repo}/issues/{pr_number}/comments?per_page=100'
        
        # Make truly parallel requests using asyncio.gather
        commits_data, reviews_data, review_comments_data, issue_comments_data = await asyncio.gather(
            fetch_paginated_data(commits_url, headers),
            fetch_paginated_data(reviews_url, headers),
            fetch_paginated_data(review_comments_url, headers),
            fetch_paginated_data(issue_comments_url, headers)
        )
        
        timeline_data = {
            'commits': commits_data,
            'reviews': reviews_data,
            'review_comments': review_comments_data,
            'issue_comments': issue_comments_data
        }
        
        # Cache the result for future requests
        set_timeline_cache(owner, repo, pr_number, timeline_data)
        
        return timeline_data
    except Exception as e:
        raise Exception(f"Error fetching timeline data: {str(e)}")


def build_pr_timeline(timeline_data):
    """
    Build unified chronological timeline from PR events
    
    Args:
        timeline_data: Dict with commits, reviews, review_comments, issue_comments
    
    Returns:
        List of event dicts sorted by timestamp:
        {
            'type': 'commit' | 'review' | 'review_comment' | 'issue_comment',
            'timestamp': datetime object,
            'author': str,
            'data': dict with event-specific data
        }
    """
    events = []
    
    # Process commits
    for commit in timeline_data.get('commits', []):
        try:
            commit_data = commit.get('commit', {})
            author_data = commit_data.get('author', {})
            
            events.append({
                'type': 'commit',
                'timestamp': parse_github_timestamp(author_data.get('date', '')),
                'author': commit.get('author', {}).get('login', author_data.get('name', 'Unknown')),
                'data': {
                    'sha': commit.get('sha', '')[:7],
                    'message': commit_data.get('message', '').split('\n')[0]  # First line only
                }
            })
        except Exception:
            continue  # Skip malformed commits
    
    # Process reviews
    for review in timeline_data.get('reviews', []):
        try:
            # Skip pending reviews
            if review.get('state') == 'PENDING':
                continue
            
            events.append({
                'type': 'review',
                'timestamp': parse_github_timestamp(review.get('submitted_at', '')),
                'author': review.get('user', {}).get('login', 'Unknown'),
                'data': {
                    'state': review.get('state', ''),  # APPROVED, CHANGES_REQUESTED, COMMENTED
                    'body': review.get('body', '')
                }
            })
        except Exception:
            continue
    
    # Process review comments (inline code comments)
    for comment in timeline_data.get('review_comments', []):
        try:
            events.append({
                'type': 'review_comment',
                'timestamp': parse_github_timestamp(comment.get('created_at', '')),
                'author': comment.get('user', {}).get('login', 'Unknown'),
                'data': {
                    'body': comment.get('body', ''),
                    'path': comment.get('path', ''),
                    'in_reply_to': comment.get('in_reply_to_id')
                }
            })
        except Exception:
            continue
    
    # Process issue comments (general PR comments)
    for comment in timeline_data.get('issue_comments', []):
        try:
            events.append({
                'type': 'issue_comment',
                'timestamp': parse_github_timestamp(comment.get('created_at', '')),
                'author': comment.get('user', {}).get('login', 'Unknown'),
                'data': {
                    'body': comment.get('body', '')
                }
            })
        except Exception:
            continue
    
    # Sort all events by timestamp
    events.sort(key=lambda x: x['timestamp'])
    
    return events
