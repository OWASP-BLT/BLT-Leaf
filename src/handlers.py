"""HTTP request handlers for BLT-Leaf."""

from js import Response, fetch, Headers, Object, URL
from pyodide.ffi import to_js
import json
import hashlib
import hmac
from datetime import datetime, timezone

from .database import get_db, upsert_pr
from .github_api import fetch_pr_data, fetch_paginated_data, fetch_pr_timeline_data
from .analyzers import parse_pr_url, parse_repo_url, build_pr_timeline, analyze_review_progress, classify_review_health, calculate_pr_readiness
from .cache import check_rate_limit, get_readiness_cache, set_readiness_cache, invalidate_readiness_cache, invalidate_timeline_cache, _READINESS_RATE_LIMIT, _READINESS_RATE_WINDOW, _READINESS_CACHE_TTL, _rate_limit_cache, _RATE_LIMIT_CACHE_TTL


async def handle_add_pr(request, env):
    """
    Handle adding a new PR or importing all PRs from a repo.
    
    Security Hardening (Issue #45):
    - Malformed JSON error handling
    - Type validation for pr_url parameter
    - Proper error handling for parse_pr_url ValueError
    """
    try:
        # Handle malformed JSON gracefully
        try:
            data = (await request.json()).to_py()
        except Exception:
            return Response.new(
                json.dumps({'error': 'Malformed JSON payload'}),
                {'status': 400, 'headers': {'Content-Type': 'application/json'}}
            )
        
        pr_url = data.get('pr_url')
        add_all = data.get('add_all', False)
        # Capture token from header
        user_token = request.headers.get('x-github-token')
        
        # Type validation for pr_url
        if not pr_url or not isinstance(pr_url, str):
            return Response.new(
                json.dumps({'error': 'A valid GitHub PR URL is required'}),
                {'status': 400, 'headers': {'Content-Type': 'application/json'}}
            )
        
        db = get_db(env)
        
        if add_all:
            # Add all prs (in bulk)
            parsed = parse_repo_url(pr_url)
            if not parsed:
                return Response.new(json.dumps({'error': 'Invalid GitHub Repository URL'}), 
                                  {'status': 400, 'headers': {'Content-Type': 'application/json'}})
            
            owner, repo = parsed['owner'], parsed['repo']
            
            # Prepare headers for paginated fetching
            headers_dict = {
                'User-Agent': 'PR-Tracker/1.0',
                'Accept': 'application/vnd.github+json',
                'X-GitHub-Api-Version': '2022-11-28'
            }
            if user_token:
                headers_dict['Authorization'] = f'Bearer {user_token}'
            
            headers = Headers.new(to_js(headers_dict, dict_converter=Object.fromEntries))
            
            # Fetch all open PRs for the repo using pagination (supports unlimited PRs)
            list_url = f"https://api.github.com/repos/{owner}/{repo}/pulls?state=open&per_page=100"
            
            try:
                prs_list = await fetch_paginated_data(list_url, headers)
            except Exception as e:
                error_msg = str(e)
                if 'status=403' in error_msg:
                    return Response.new(json.dumps({'error': 'Rate Limit Exceeded'}), 
                                      {'status': 403, 'headers': {'Content-Type': 'application/json'}})
                return Response.new(json.dumps({'error': f'Failed to fetch repo PRs: {error_msg}'}), 
                                  {'status': 400, 'headers': {'Content-Type': 'application/json'}})
            added_count = 0
            ts = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
            
            for item in prs_list:
                pr_data = {
                    'title': item.get('title', ''), 
                    'state': 'open', 
                    'is_merged': 0,
                    'mergeable_state': 'unknown', 
                    'files_changed': 0,
                    'author_login': item['user']['login'], 
                    'author_avatar': item['user']['avatar_url'],
                    'repo_owner_avatar': '',
                    'checks_passed': 0, 
                    'checks_failed': 0, 
                    'checks_skipped': 0,
                    'review_status': 'pending', 
                    'last_updated_at': item.get('updated_at', ts)
                }
                
                await upsert_pr(db, item['html_url'], owner, repo, item['number'], pr_data)
                added_count += 1
            
            return Response.new(json.dumps({'success': True, 'message': f'Successfully imported {added_count} PRs'}), 
                              {'headers': {'Content-Type': 'application/json'}})

        else:
            # Add single pr
            # Catch ValueError from parse_pr_url
            try:
                parsed = parse_pr_url(pr_url)
            except ValueError as e:
                return Response.new(
                    json.dumps({'error': str(e)}),
                    {'status': 400, 'headers': {'Content-Type': 'application/json'}}
                )
            
            # Fetch PR data 
            pr_data = await fetch_pr_data(parsed['owner'], parsed['repo'], parsed['pr_number'], user_token)
            
            if not pr_data:
                # If null returned
                return Response.new(json.dumps({'error': 'Failed to fetch PR data (Rate Limit or Not Found)'}), 
                                  {'status': 403, 'headers': {'Content-Type': 'application/json'}})
            
            if pr_data['is_merged'] or pr_data['state'] == 'closed':
                return Response.new(json.dumps({'error': 'Cannot add merged/closed PRs'}), 
                                  {'status': 400, 'headers': {'Content-Type': 'application/json'}})
            
            await upsert_pr(db, pr_url, parsed['owner'], parsed['repo'], parsed['pr_number'], pr_data)
            
            return Response.new(json.dumps({'success': True, 'data': pr_data}), 
                              {'headers': {'Content-Type': 'application/json'}})

    except Exception as e:
        # Generic error message to prevent information disclosure
        print(f"Internal error in handle_add_pr: {type(e).__name__}: {str(e)}")
        return Response.new(
            json.dumps({'error': 'Internal server error'}),
            {'status': 500, 'headers': {'Content-Type': 'application/json'}}
        )


async def handle_list_prs(env, repo_filter=None):
    """List all PRs, optionally filtered by repo."""
    try:
        db = get_db(env)
        if repo_filter:
            parts = repo_filter.split('/')
            if len(parts) == 2:
                stmt = db.prepare('''
                    SELECT * FROM prs 
                    WHERE repo_owner = ? AND repo_name = ?
                    AND is_merged = 0 AND state = 'open'
                    ORDER BY last_updated_at DESC
                ''').bind(parts[0], parts[1])
            else:
                stmt = db.prepare('''
                    SELECT * FROM prs 
                    WHERE is_merged = 0 AND state = 'open'
                    ORDER BY last_updated_at DESC
                ''')
        else:
            stmt = db.prepare('''
                SELECT * FROM prs 
                WHERE is_merged = 0 AND state = 'open'
                ORDER BY last_updated_at DESC
            ''')
        
        result = await stmt.all()
        # Convert JS Array to Python list
        prs = result.results.to_py() if hasattr(result, 'results') else []
        
        return Response.new(json.dumps({'prs': prs}), 
                          {'headers': {'Content-Type': 'application/json'}})
    except Exception as e:
        return Response.new(json.dumps({'error': f"{type(e).__name__}: {str(e)}"}), 
                          {'status': 500, 'headers': {'Content-Type': 'application/json'}})


async def handle_list_repos(env):
    """List all unique repos with count of open PRs"""
    try:
        db = get_db(env)
        stmt = db.prepare('''
            SELECT DISTINCT repo_owner, repo_name, 
                   COUNT(*) as pr_count
            FROM prs 
            WHERE is_merged = 0 AND state = 'open'
            GROUP BY repo_owner, repo_name
            ORDER BY repo_owner, repo_name
        ''')
        
        result = await stmt.all()
        # Convert JS Array to Python list
        repos = result.results.to_py() if hasattr(result, 'results') else []
        
        return Response.new(json.dumps({'repos': repos}), 
                          {'headers': {'Content-Type': 'application/json'}})
    except Exception as e:
        return Response.new(json.dumps({'error': f"{type(e).__name__}: {str(e)}"}), 
                          {'status': 500, 'headers': {'Content-Type': 'application/json'}})


async def handle_refresh_pr(request, env):
    """Refresh a specific PR's data"""
    try:
        data = (await request.json()).to_py()
        pr_id = data.get('pr_id')
        user_token = request.headers.get('x-github-token')
        
        if not pr_id:
            return Response.new(json.dumps({'error': 'PR ID is required'}), 
                              {'status': 400, 'headers': {'Content-Type': 'application/json'}})
        
        # Get PR URL from database
        db = get_db(env)
        stmt = db.prepare('SELECT pr_url, repo_owner, repo_name, pr_number FROM prs WHERE id = ?').bind(pr_id)
        result = await stmt.first()
        
        if not result:
            return Response.new(json.dumps({'error': 'PR not found'}), 
                              {'status': 404, 'headers': {'Content-Type': 'application/json'}})
        
        # Convert JsProxy to Python dict to make it subscriptable
        result = result.to_py()
        
        # Fetch fresh data from GitHub (with Token)
        pr_data = await fetch_pr_data(result['repo_owner'], result['repo_name'], result['pr_number'], user_token)
        if not pr_data:
            return Response.new(json.dumps({'error': 'Failed to fetch PR data from GitHub'}), 
                              {'status': 403, 'headers': {'Content-Type': 'application/json'}})
        
        # Check if PR is now merged or closed - delete it from database
        if pr_data['is_merged'] or pr_data['state'] == 'closed':
            # Invalidate caches since PR state changed
            await invalidate_readiness_cache(env, pr_id)
            invalidate_timeline_cache(result['repo_owner'], result['repo_name'], result['pr_number'])
            
            # Delete the PR from database
            delete_stmt = db.prepare('DELETE FROM prs WHERE id = ?').bind(pr_id)
            await delete_stmt.run()
            
            status_msg = 'merged' if pr_data['is_merged'] else 'closed'
            return Response.new(json.dumps({
                'success': True, 
                'removed': True,
                'message': f'PR has been {status_msg} and removed from tracking'
            }), {'headers': {'Content-Type': 'application/json'}})
        
        await upsert_pr(db, result['pr_url'], result['repo_owner'], result['repo_name'], result['pr_number'], pr_data)
        
        # Invalidate caches after successful refresh
        # This ensures cached results don't become stale after new commits or review activity
        await invalidate_readiness_cache(env, pr_id)
        invalidate_timeline_cache(result['repo_owner'], result['repo_name'], result['pr_number'])
        
        return Response.new(json.dumps({'success': True, 'data': pr_data}), 
                          {'headers': {'Content-Type': 'application/json'}})
    except Exception as e:
        return Response.new(json.dumps({'error': f"{type(e).__name__}: {str(e)}"}), 
                          {'status': 500, 'headers': {'Content-Type': 'application/json'}})


async def handle_rate_limit(env):
    """Fetch GitHub API rate limit status
    
    Args:
        env: Cloudflare Worker environment object containing bindings
        
    Returns:
        Response object with JSON containing:
            - limit: Maximum number of requests per hour
            - remaining: Number of requests remaining
            - reset: Unix timestamp when the limit resets
            - used: Number of requests used
    """
    global _rate_limit_cache
    
    try:
        # Check cache first to avoid excessive API calls
        # Use JavaScript Date API for Cloudflare Workers compatibility
        from js import Date
        current_time = Date.now() / 1000  # Convert milliseconds to seconds
        
        if _rate_limit_cache['data'] and (current_time - _rate_limit_cache['timestamp']) < _RATE_LIMIT_CACHE_TTL:
            # Return cached data
            return Response.new(
                json.dumps(_rate_limit_cache['data']), 
                {'headers': {
                    'Content-Type': 'application/json',
                    'Cache-Control': f'public, max-age={_RATE_LIMIT_CACHE_TTL}'
                }}
            )
        
        # Fetch rate limit from GitHub API
        from .github_api import fetch_with_headers
        rate_limit_url = "https://api.github.com/rate_limit"
        response = await fetch_with_headers(rate_limit_url)
        
        if response.status != 200:
            return Response.new(json.dumps({'error': f'GitHub API Error: {response.status}'}), 
                              {'status': response.status, 'headers': {'Content-Type': 'application/json'}})
        
        rate_data = (await response.json()).to_py()
        # Extract core rate limit info
        core_limit = rate_data.get('resources', {}).get('core', {})
        
        result = {
            'limit': core_limit.get('limit', 60),
            'remaining': core_limit.get('remaining', 0),
            'reset': core_limit.get('reset', 0),
            'used': core_limit.get('used', 0)
        }
        
        # Update cache
        _rate_limit_cache['data'] = result
        _rate_limit_cache['timestamp'] = current_time
        
        return Response.new(
            json.dumps(result), 
            {'headers': {'Content-Type': 'application/json', 'Cache-Control': f'public, max-age={_RATE_LIMIT_CACHE_TTL}'}}
        )
    except Exception as e:
        return Response.new(json.dumps({'error': f"{type(e).__name__}: {str(e)}"}), 
                          {'status': 500, 'headers': {'Content-Type': 'application/json'}})


async def handle_status(env):
    """Check database status"""
    try:
        db = get_db(env)
        # If we got here, database is configured (would have thrown exception otherwise)
        return Response.new(json.dumps({
            'database_configured': True,
            'environment': getattr(env, 'ENVIRONMENT', 'unknown')
        }), {'headers': {'Content-Type': 'application/json'}})
    except Exception as e:
        # Database not configured
        return Response.new(json.dumps({
            'database_configured': False,
            'error': str(e),
            'environment': getattr(env, 'ENVIRONMENT', 'unknown')
        }), {'headers': {'Content-Type': 'application/json'}})


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


async def handle_github_webhook(request, env):
    """
    POST /api/github/webhook
    Handle GitHub webhook events for PR state changes.
    
    Supported events:
    - pull_request: closed, reopened, synchronize, edited
    - pull_request_review: submitted, edited, dismissed
    - check_run: completed, requested_action
    
    Security:
    - Verifies GitHub webhook signature using WEBHOOK_SECRET
    - Validates event types before processing
    
    When a PR is closed or merged:
    - Removes the PR from the database
    - Returns event data for frontend to animate removal
    
    When a PR is updated:
    - Refreshes PR data in the database
    - Returns updated PR data for frontend
    """
    try:
        # Get webhook secret from environment
        webhook_secret = getattr(env, 'GITHUB_WEBHOOK_SECRET', None)
        
        # Get raw request body for signature verification
        raw_body = await request.text()
        
        # Verify webhook signature
        if not await verify_github_signature(request, raw_body, webhook_secret):
            return Response.new(
                json.dumps({'error': 'Invalid webhook signature'}),
                {'status': 401, 'headers': {'Content-Type': 'application/json'}}
            )
        
        # Parse webhook payload
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            return Response.new(
                json.dumps({'error': 'Invalid JSON payload'}),
                {'status': 400, 'headers': {'Content-Type': 'application/json'}}
            )
        
        # Get event type from header
        event_type = request.headers.get('x-github-event')
        
        if event_type == 'pull_request':
            action = payload.get('action')
            pr_data = payload.get('pull_request', {})
            repo_data = payload.get('repository', {})
            
            # Extract PR details
            pr_number = pr_data.get('number')
            repo_owner = repo_data.get('owner', {}).get('login')
            repo_name = repo_data.get('name')
            state = pr_data.get('state')
            merged = pr_data.get('merged', False)
            
            if not all([pr_number, repo_owner, repo_name]):
                return Response.new(
                    json.dumps({'error': 'Missing required PR data'}),
                    {'status': 400, 'headers': {'Content-Type': 'application/json'}}
                )
            
            # Find the PR in our database
            db = get_db(env)
            pr_url = f"https://github.com/{repo_owner}/{repo_name}/pull/{pr_number}"
            result = await db.prepare(
                'SELECT id FROM prs WHERE pr_url = ?'
            ).bind(pr_url).first()
            
            if not result:
                # PR not being tracked - ignore this webhook
                return Response.new(
                    json.dumps({
                        'success': True,
                        'message': 'PR not tracked, ignoring webhook'
                    }),
                    {'headers': {'Content-Type': 'application/json'}}
                )
            
            pr_id = result.to_py()['id']
            
            # Handle closed/merged PRs - remove from database
            if action == 'closed' or merged or state == 'closed':
                # Invalidate caches
                await invalidate_readiness_cache(env, pr_id)
                invalidate_timeline_cache(repo_owner, repo_name, pr_number)
                
                # Delete the PR
                await db.prepare('DELETE FROM prs WHERE id = ?').bind(pr_id).run()
                
                status_msg = 'merged' if merged else 'closed'
                return Response.new(
                    json.dumps({
                        'success': True,
                        'event': 'pr_removed',
                        'pr_id': pr_id,
                        'pr_number': pr_number,
                        'status': status_msg,
                        'message': f'PR #{pr_number} has been {status_msg} and removed from tracking'
                    }),
                    {'headers': {'Content-Type': 'application/json'}}
                )
            
            # Handle reopened PRs - re-add to tracking if it was tracked before
            elif action == 'reopened':
                # Fetch fresh PR data
                fetched_pr_data = await fetch_pr_data(repo_owner, repo_name, pr_number)
                if fetched_pr_data:
                    await upsert_pr(db, pr_url, repo_owner, repo_name, pr_number, fetched_pr_data)
                    # Invalidate caches
                    await invalidate_readiness_cache(env, pr_id)
                    invalidate_timeline_cache(repo_owner, repo_name, pr_number)
                    
                    return Response.new(
                        json.dumps({
                            'success': True,
                            'event': 'pr_reopened',
                            'pr_id': pr_id,
                            'pr_number': pr_number,
                            'data': fetched_pr_data,
                            'message': f'PR #{pr_number} has been reopened'
                        }),
                        {'headers': {'Content-Type': 'application/json'}}
                    )
            
            # Handle synchronized (new commits) or edited PRs - update data
            elif action in ['synchronize', 'edited']:
                # Fetch fresh PR data
                fetched_pr_data = await fetch_pr_data(repo_owner, repo_name, pr_number)
                if fetched_pr_data:
                    await upsert_pr(db, pr_url, repo_owner, repo_name, pr_number, fetched_pr_data)
                    # Invalidate caches to force fresh analysis
                    await invalidate_readiness_cache(env, pr_id)
                    invalidate_timeline_cache(repo_owner, repo_name, pr_number)
                    
                    return Response.new(
                        json.dumps({
                            'success': True,
                            'event': 'pr_updated',
                            'pr_id': pr_id,
                            'pr_number': pr_number,
                            'data': fetched_pr_data,
                            'message': f'PR #{pr_number} has been updated'
                        }),
                        {'headers': {'Content-Type': 'application/json'}}
                    )
        
        # Handle other event types (for future expansion)
        elif event_type in ['pull_request_review', 'check_run', 'check_suite']:
            # For now, just acknowledge these events
            # In the future, we could update specific fields without full refresh
            return Response.new(
                json.dumps({
                    'success': True,
                    'message': f'Received {event_type} event, no action taken'
                }),
                {'headers': {'Content-Type': 'application/json'}}
            )
        
        # Unknown event type
        return Response.new(
            json.dumps({
                'success': True,
                'message': f'Received {event_type} event, no handler configured'
            }),
            {'headers': {'Content-Type': 'application/json'}}
        )
        
    except Exception as e:
        print(f"Error handling webhook: {type(e).__name__}: {str(e)}")
        return Response.new(
            json.dumps({'error': f"{type(e).__name__}: {str(e)}"}),
            {'status': 500, 'headers': {'Content-Type': 'application/json'}}
        )


async def handle_pr_timeline(request, env, path):
    """
    GET /api/prs/{id}/timeline
    Fetch and return the full timeline for a PR
    
    Features:
    - Application-level rate limiting (10 requests/minute per IP)
    """
    try:
        # Extract PR ID from path: /api/prs/123/timeline
        pr_id = path.split('/')[3]  # Split by / and get the ID
        
        # Get client IP for rate limiting
        client_ip = (
            request.headers.get('cf-connecting-ip') or
            (request.headers.get('x-forwarded-for') or '').split(',')[0].strip() or
            request.headers.get('x-real-ip') or
            'unknown'
        )
        
        # Check rate limit
        allowed, retry_after = check_rate_limit(client_ip)
        if not allowed:
            return Response.new(
                json.dumps({
                    'error': 'Rate limit exceeded',
                    'message': f'Too many requests. Please try again in {retry_after} seconds.',
                    'retry_after': retry_after
                }),
                {
                    'status': 429,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Retry-After': str(retry_after),
                        'X-RateLimit-Limit': str(_READINESS_RATE_LIMIT),
                        'X-RateLimit-Window': str(_READINESS_RATE_WINDOW)
                    }
                }
            )
        
        # Get PR details from database
        db = get_db(env)
        result = await db.prepare(
            'SELECT * FROM prs WHERE id = ?'
        ).bind(pr_id).first()
        
        if not result:
            return Response.new(json.dumps({'error': 'PR not found'}), 
                              {'status': 404, 'headers': {'Content-Type': 'application/json'}})
        
        pr = result.to_py()
        
        # Fetch timeline data from GitHub
        timeline_data = await fetch_pr_timeline_data(
            pr['repo_owner'],
            pr['repo_name'],
            pr['pr_number']
        )
        
        # Build unified timeline
        timeline = build_pr_timeline(timeline_data)
        
        # Convert datetime objects to ISO strings for JSON serialization
        timeline_json = []
        for event in timeline:
            event_copy = event.copy()
            event_copy['timestamp'] = event['timestamp'].isoformat()
            timeline_json.append(event_copy)
        
        return Response.new(json.dumps({
            'pr': {
                'id': pr['id'],
                'title': pr['title'],
                'author': pr['author_login'],
                'repo': f"{pr['repo_owner']}/{pr['repo_name']}",
                'number': pr['pr_number']
            },
            'timeline': timeline_json,
            'event_count': len(timeline_json)
        }), 
                          {'headers': {'Content-Type': 'application/json'}})
    except Exception as e:
        return Response.new(json.dumps({'error': f"{type(e).__name__}: {str(e)}"}), 
                          {'status': 500, 'headers': {'Content-Type': 'application/json'}})


async def handle_pr_review_analysis(request, env, path):
    """
    GET /api/prs/{id}/review-analysis
    Analyze PR review progress and health
    
    Features:
    - Application-level rate limiting (10 requests/minute per IP)
    """
    try:
        # Extract PR ID from path: /api/prs/123/review-analysis
        pr_id = path.split('/')[3]
        
        # Get client IP for rate limiting
        client_ip = (
            request.headers.get('cf-connecting-ip') or
            (request.headers.get('x-forwarded-for') or '').split(',')[0].strip() or
            request.headers.get('x-real-ip') or
            'unknown'
        )
        
        # Check rate limit
        allowed, retry_after = check_rate_limit(client_ip)
        if not allowed:
            return Response.new(
                json.dumps({
                    'error': 'Rate limit exceeded',
                    'message': f'Too many requests. Please try again in {retry_after} seconds.',
                    'retry_after': retry_after
                }),
                {
                    'status': 429,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Retry-After': str(retry_after),
                        'X-RateLimit-Limit': str(_READINESS_RATE_LIMIT),
                        'X-RateLimit-Window': str(_READINESS_RATE_WINDOW)
                    }
                }
            )
        
        # Get PR details from database
        db = get_db(env)
        result = await db.prepare(
            'SELECT * FROM prs WHERE id = ?'
        ).bind(pr_id).first()
        
        if not result:
            return Response.new(json.dumps({'error': 'PR not found'}), 
                              {'status': 404, 'headers': {'Content-Type': 'application/json'}})
        
        pr = result.to_py()
        
        # Fetch timeline data from GitHub
        timeline_data = await fetch_pr_timeline_data(
            pr['repo_owner'],
            pr['repo_name'],
            pr['pr_number']
        )
        
        # Build unified timeline
        timeline = build_pr_timeline(timeline_data)
        
        # Analyze review progress
        review_data = analyze_review_progress(timeline, pr['author_login'])
        
        # Classify review health
        classification, score = classify_review_health(review_data)
        
        return Response.new(json.dumps({
            'pr': {
                'id': pr['id'],
                'title': pr['title'],
                'author': pr['author_login'],
                'repo': f"{pr['repo_owner']}/{pr['repo_name']}",
                'number': pr['pr_number']
            },
            'review_analysis': {
                'classification': classification,
                'score': score,
                'score_display': f"{score}%",
                'total_feedback': review_data['total_feedback_count'],
                'responded_feedback': review_data['responded_count'],
                'response_rate': review_data['response_rate'],
                'response_rate_display': f"{int(review_data['response_rate'] * 100)}%",
                'awaiting_author': review_data['awaiting_author'],
                'awaiting_reviewer': review_data['awaiting_reviewer'],
                'stale_feedback_count': len(review_data['stale_feedback']),
                'stale_feedback': review_data['stale_feedback'],
                'latest_review_state': review_data['latest_review_state'],
                'last_reviewer_action': review_data['last_reviewer_action'],
                'last_author_action': review_data['last_author_action']
            },
            'feedback_loops': review_data['feedback_loops']
        }), 
                          {'headers': {'Content-Type': 'application/json'}})
    except Exception as e:
        return Response.new(json.dumps({'error': f"{type(e).__name__}: {str(e)}"}), 
                          {'status': 500, 'headers': {'Content-Type': 'application/json'}})


async def handle_pr_readiness(request, env, path):
    """
    GET /api/prs/{id}/readiness
    Calculate overall PR readiness combining CI and review health
    
    Features:
    - Application-level rate limiting (10 requests/minute per IP)
    - Response caching (10 minutes TTL)
    - Cache invalidation on PR refresh
    """
    try:
        # Extract PR ID from path: /api/prs/123/readiness
        pr_id = path.split('/')[3]
        
        # Get client IP for rate limiting
        # Try multiple headers to support different proxy configurations
        client_ip = (
            request.headers.get('cf-connecting-ip') or  # Cloudflare
            (request.headers.get('x-forwarded-for') or '').split(',')[0].strip() or
            request.headers.get('x-real-ip') or
            'unknown'
        )
        
        # Check rate limit
        allowed, retry_after = check_rate_limit(client_ip)
        if not allowed:
            return Response.new(
                json.dumps({
                    'error': 'Rate limit exceeded',
                    'message': f'Too many requests. Please try again in {retry_after} seconds.',
                    'retry_after': retry_after
                }),
                {
                    'status': 429,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Retry-After': str(retry_after),
                        'X-RateLimit-Limit': str(_READINESS_RATE_LIMIT),
                        'X-RateLimit-Window': str(_READINESS_RATE_WINDOW)
                    }
                }
            )
        
        # Check cache first
        cached_result = await get_readiness_cache(env, pr_id)
        if cached_result:
            # Return cached response with cache headers
            return Response.new(
                json.dumps(cached_result),
                {
                    'headers': {
                        'Content-Type': 'application/json',
                        'X-Cache': 'HIT',
                        'Cache-Control': f'private, max-age={_READINESS_CACHE_TTL}'
                    }
                }
            )
        
        # Get PR details from database
        db = get_db(env)
        result = await db.prepare(
            'SELECT * FROM prs WHERE id = ?'
        ).bind(pr_id).first()
        
        if not result:
            return Response.new(json.dumps({'error': 'PR not found'}), 
                              {'status': 404, 'headers': {'Content-Type': 'application/json'}})
        
        pr = result.to_py()
        
        # Fetch timeline data from GitHub
        timeline_data = await fetch_pr_timeline_data(
            pr['repo_owner'],
            pr['repo_name'],
            pr['pr_number']
        )
        
        # Build unified timeline
        timeline = build_pr_timeline(timeline_data)
        
        # Analyze review progress
        review_data = analyze_review_progress(timeline, pr['author_login'])
        
        # Classify review health
        review_classification, review_score = classify_review_health(review_data)
        
        # Calculate combined readiness
        readiness = calculate_pr_readiness(pr, review_classification, review_score)
        
        # Build response data with percentage formatting
        response_data = {
            'pr': {
                'id': pr['id'],
                'title': pr['title'],
                'author': pr['author_login'],
                'repo': f"{pr['repo_owner']}/{pr['repo_name']}",
                'number': pr['pr_number'],
                'state': pr['state'],
                'is_merged': pr['is_merged'] == 1,
                'mergeable_state': pr['mergeable_state'],
                'files_changed': pr['files_changed']
            },
            'readiness': {
                **readiness,
                'overall_score_display': f"{readiness['overall_score']}%",
                'ci_score_display': f"{readiness['ci_score']}%",
                'review_score_display': f"{readiness.get('review_score', review_score)}%"
            },
            'review_health': {
                'classification': review_classification,
                'score': review_score,
                'score_display': f"{review_score}%",
                'total_feedback': review_data['total_feedback_count'],
                'responded_feedback': review_data['responded_count'],
                'response_rate': review_data['response_rate'],
                'response_rate_display': f"{int(review_data['response_rate'] * 100)}%",
                'stale_feedback_count': len(review_data['stale_feedback'])
            },
            'ci_checks': {
                'passed': pr['checks_passed'],
                'failed': pr['checks_failed'],
                'skipped': pr['checks_skipped']
            }
        }
        
        # Cache the result
        await set_readiness_cache(env, pr_id, response_data)
        
        return Response.new(
            json.dumps(response_data),
            {
                'headers': {
                    'Content-Type': 'application/json',
                    'X-Cache': 'MISS',
                    'Cache-Control': f'private, max-age={_READINESS_CACHE_TTL}'
                }
            }
        )
    except Exception as e:
        return Response.new(json.dumps({'error': f"{type(e).__name__}: {str(e)}"}), 
                          {'status': 500, 'headers': {'Content-Type': 'application/json'}})
