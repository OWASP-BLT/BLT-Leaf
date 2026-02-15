from js import Response, fetch, Headers, URL, Object, Date
from pyodide.ffi import to_js
import json
import re
from datetime import datetime, timezone

# Track if schema initialization has been attempted in this worker instance
# This is safe in Cloudflare Workers Python as each isolate runs single-threaded
_schema_init_attempted = False

# In-memory cache for rate limit data (per worker isolate)
_rate_limit_cache = {
    'data': None,
    'timestamp': 0
}
# Cache TTL in seconds (5 minutes)
_RATE_LIMIT_CACHE_TTL = 300

def verify_auth_token(request):
    """Extract and verify GitHub username from Authorization header
    
    Expected format: "Bearer {username}"
    The username is passed directly without encoding for simplicity.
    In production, this should be a proper JWT or session token.
    
    Username validation follows GitHub's requirements:
    - 1-39 characters long
    - Alphanumeric characters and hyphens only
    - Must start and end with alphanumeric character
    """
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return None
    
    try:
        # Expected format: "Bearer username"
        if not auth_header.startswith('Bearer '):
            return None
        
        username = auth_header[7:]  # Remove "Bearer " prefix
        
        # Validate GitHub username format
        # Length must be 1-39 characters
        if not username or len(username) < 1 or len(username) > 39:
            return None
        
        # Must contain only alphanumeric characters and hyphens
        if not all(c.isalnum() or c == '-' for c in username):
            return None
        
        # Must start and end with alphanumeric character
        if not username[0].isalnum() or not username[-1].isalnum():
            return None
        
        return username
    except Exception:
        return None

def parse_pr_url(pr_url):
    """Parse GitHub PR URL to extract owner, repo, and PR number"""
    pattern = r'https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)'
    match = re.match(pattern, pr_url)
    if match:
        return {
            'owner': match.group(1),
            'repo': match.group(2),
            'pr_number': int(match.group(3))
        }
    return None

def get_db(env):
    """Helper to get DB binding from env, handling different env types.
    
    Raises an exception if database is not configured.
    """
    # Try common binding names
    for name in ['pr_tracker', 'DB']:
        # Try attribute access
        if hasattr(env, name):
            return getattr(env, name)
        # Try dict access
        if hasattr(env, '__getitem__'):
            try:
                return env[name]
            except (KeyError, TypeError):
                pass
    
    # Database not configured - raise error
    print(f"DEBUG: env attributes: {dir(env)}")
    raise Exception("Database binding 'pr_tracker' or 'DB' not found in env. Please configure a D1 database.")

async def record_pr_history(db, pr_id, action_type, actor=None, description=None, before_state=None, after_state=None):
    """Record a PR history entry
    
    Args:
        db: Database connection
        pr_id: PR ID
        action_type: Type of action ('refresh', 'state_change', 'review_change', 'checks_change', 'added')
        actor: GitHub username who performed the action (optional)
        description: Human-readable description of the change (optional)
        before_state: JSON string of state before change (optional)
        after_state: JSON string of state after change (optional)
    """
    current_timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    
    stmt = db.prepare('''
        INSERT INTO pr_history (pr_id, action_type, actor, description, before_state, after_state, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''').bind(pr_id, action_type, actor, description, before_state, after_state, current_timestamp)
    
    await stmt.run()


async def init_database_schema(env):
    """Initialize database schema if it doesn't exist.
    
    This function is idempotent and safe to call multiple times.
    Uses CREATE TABLE IF NOT EXISTS to avoid errors on existing tables.
    Includes migration logic to add missing columns to existing tables.
    A module-level flag prevents redundant calls within the same worker instance.
    """
    global _schema_init_attempted
    
    # Skip if already attempted in this worker instance
    if _schema_init_attempted:
        return
    
    _schema_init_attempted = True
    
    try:
        db = get_db(env)
        
        # Create the prs table (idempotent with IF NOT EXISTS)
        create_table = db.prepare('''
            CREATE TABLE IF NOT EXISTS prs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pr_url TEXT NOT NULL UNIQUE,
                repo_owner TEXT NOT NULL,
                repo_name TEXT NOT NULL,
                pr_number INTEGER NOT NULL,
                title TEXT,
                state TEXT,
                is_merged INTEGER DEFAULT 0,
                mergeable_state TEXT,
                files_changed INTEGER DEFAULT 0,
                author_login TEXT,
                author_avatar TEXT,
                checks_passed INTEGER DEFAULT 0,
                checks_failed INTEGER DEFAULT 0,
                checks_skipped INTEGER DEFAULT 0,
                review_status TEXT,
                last_updated_at TEXT,
                last_refreshed_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await create_table.run()
        
        # Migration: Add last_refreshed_at column if it doesn't exist
        # Check if column exists by querying PRAGMA table_info
        try:
            pragma_result = db.prepare('PRAGMA table_info(prs)')
            columns_result = await pragma_result.all()
            columns = columns_result.results.to_py() if hasattr(columns_result, 'results') else []
            
            # Check if last_refreshed_at column exists
            column_names = [col['name'] for col in columns if isinstance(col, dict)]
            if 'last_refreshed_at' not in column_names:
                print("Migrating database: Adding last_refreshed_at column")
                alter_table = db.prepare('ALTER TABLE prs ADD COLUMN last_refreshed_at TEXT')
                await alter_table.run()
        except Exception as migration_error:
            # Column may already exist or migration failed - log but continue
            print(f"Note: Migration check for last_refreshed_at: {str(migration_error)}")
        
        # Create indexes (idempotent with IF NOT EXISTS)
        index1 = db.prepare('CREATE INDEX IF NOT EXISTS idx_repo ON prs(repo_owner, repo_name)')
        await index1.run()
        
        index2 = db.prepare('CREATE INDEX IF NOT EXISTS idx_pr_number ON prs(pr_number)')
        await index2.run()
        
        # Create pr_history table (idempotent with IF NOT EXISTS)
        # This replaces the old refresh_history table with a more comprehensive history tracking
        create_pr_history = db.prepare('''
            CREATE TABLE IF NOT EXISTS pr_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pr_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                actor TEXT,
                description TEXT,
                before_state TEXT,
                after_state TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (pr_id) REFERENCES prs(id) ON DELETE CASCADE
            )
        ''')
        await create_pr_history.run()
        
        # Create indexes for pr_history table
        index3 = db.prepare('CREATE INDEX IF NOT EXISTS idx_history_pr_id ON pr_history(pr_id)')
        await index3.run()
        
        index4 = db.prepare('CREATE INDEX IF NOT EXISTS idx_history_actor ON pr_history(actor)')
        await index4.run()
        
        index5 = db.prepare('CREATE INDEX IF NOT EXISTS idx_history_action_type ON pr_history(action_type)')
        await index5.run()
        
        index6 = db.prepare('CREATE INDEX IF NOT EXISTS idx_history_created_at ON pr_history(created_at)')
        await index6.run()
        
        # Migration: Migrate data from old refresh_history table to pr_history if it exists
        try:
            # Check if old refresh_history table exists
            check_old_table = db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name='refresh_history'")
            old_table_result = await check_old_table.first()
            
            if old_table_result:
                print("Migrating data from refresh_history to pr_history...")
                # Copy data from refresh_history to pr_history
                migrate_data = db.prepare('''
                    INSERT INTO pr_history (pr_id, action_type, actor, description, created_at)
                    SELECT pr_id, 'refresh', refreshed_by, 'PR refreshed', refreshed_at
                    FROM refresh_history
                    WHERE NOT EXISTS (
                        SELECT 1 FROM pr_history 
                        WHERE pr_history.pr_id = refresh_history.pr_id 
                        AND pr_history.created_at = refresh_history.refreshed_at
                    )
                ''')
                await migrate_data.run()
                print("Migration from refresh_history completed")
        except Exception as migration_error:
            print(f"Note: Migration from refresh_history: {str(migration_error)}")
        
    except Exception as e:
        # Log the error but don't crash - schema may already exist
        print(f"Note: Schema initialization check: {str(e)}")
        # Schema likely already exists, which is fine

async def fetch_with_headers(url, headers=None):
    """Helper to fetch with proper header handling using pyodide.ffi.to_js"""
    if headers:
        # Convert Python dict to JavaScript object using Object.fromEntries for correct mapping
        options = to_js({
            "method": "GET",
            "headers": headers
        }, dict_converter=Object.fromEntries)
        return await fetch(url, options)
    else:
        return await fetch(url)

async def fetch_pr_data(owner, repo, pr_number):
    """Fetch PR data from GitHub API"""
    headers = {
        'User-Agent': 'PR-Tracker/1.0',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28'
    }
        
    try:
        # Fetch PR details
        pr_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
        pr_response = await fetch_with_headers(pr_url, headers)
        
        if pr_response.status == 403 or pr_response.status == 429:
            rl_limit = pr_response.headers.get('x-ratelimit-limit', 'unknown')
            rl_remaining = pr_response.headers.get('x-ratelimit-remaining', 'unknown')
            error_body = await pr_response.text()
            error_body = await pr_response.text()
            print(f"DEBUG: GitHub API Error. Status: {pr_response.status}. Body: {error_body}")
            print(f"DEBUG: Sent headers due to error: User-Agent={headers.get('User-Agent', 'MISSING')}")
            raise Exception(f"GitHub API Error {pr_response.status}: {error_body} (Limit: {rl_limit}, Remaining: {rl_remaining})")
        elif pr_response.status == 404:
            raise Exception("PR not found or repository is private")
        elif pr_response.status >= 400:
            error_msg = await pr_response.text()
            raise Exception(f"GitHub API Error: {pr_response.status} {error_msg}")
            
        pr_data = (await pr_response.json()).to_py()
        
        # Fetch PR files
        files_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files"
        files_response = await fetch_with_headers(files_url, headers)
        files_data = (await files_response.json()).to_py() if files_response.status == 200 else []
        
        # Fetch PR reviews
        reviews_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
        reviews_response = await fetch_with_headers(reviews_url, headers)
        reviews_data = (await reviews_response.json()).to_py() if reviews_response.status == 200 else []
        
        # Fetch check runs
        checks_url = f"https://api.github.com/repos/{owner}/{repo}/commits/{pr_data['head']['sha']}/check-runs"
        checks_response = await fetch_with_headers(checks_url, headers)
        checks_data = (await checks_response.json()).to_py() if checks_response.status == 200 else {}
        
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
        
        # Determine review status - sort by submitted_at to get latest reviews
        review_status = 'none'
        if reviews_data:
            # Sort reviews by submitted_at to get chronological order
            sorted_reviews = sorted(reviews_data, key=lambda x: x.get('submitted_at', ''))
            
            # Get latest review per user
            latest_reviews = {}
            for review in sorted_reviews:
                user = review['user']['login']
                latest_reviews[user] = review['state']
            
            # Determine overall status: changes_requested takes precedence over approved
            if 'CHANGES_REQUESTED' in latest_reviews.values():
                review_status = 'changes_requested'
            elif 'APPROVED' in latest_reviews.values():
                review_status = 'approved'
            else:
                review_status = 'pending'
        
        return {
            'title': pr_data.get('title', ''),
            'state': pr_data.get('state', ''),
            'is_merged': 1 if pr_data.get('merged', False) else 0,
            'mergeable_state': pr_data.get('mergeable_state', ''),
            'files_changed': len(files_data) if isinstance(files_data, list) else 0,
            'author_login': pr_data['user']['login'],
            'author_avatar': pr_data['user']['avatar_url'],
            'checks_passed': checks_passed,
            'checks_failed': checks_failed,
            'checks_skipped': checks_skipped,
            'review_status': review_status,
            'last_updated_at': pr_data.get('updated_at', '')
        }
    except Exception as e:
        # Return more informative error for debugging
        error_msg = f"Error fetching PR data: {str(e)}"
        # In Cloudflare Workers, console.error is preferred
        raise Exception(error_msg)

async def handle_add_pr(request, env):
    """Handle adding a new PR"""
    try:
        data = (await request.json()).to_py()
        pr_url = data.get('pr_url')
        
        if not pr_url:
            return Response.new(json.dumps({'error': 'PR URL is required'}), 
                              {'status': 400, 'headers': {'Content-Type': 'application/json'}})
        
        # Parse PR URL
        parsed = parse_pr_url(pr_url)
        if not parsed:
            return Response.new(json.dumps({'error': 'Invalid GitHub PR URL'}), 
                              {'status': 400, 'headers': {'Content-Type': 'application/json'}})
        
        # Fetch PR data from GitHub
        pr_data = await fetch_pr_data(parsed['owner'], parsed['repo'], parsed['pr_number'])
        if not pr_data:
            return Response.new(json.dumps({'error': 'Failed to fetch PR data from GitHub'}), 
                              {'status': 500, 'headers': {'Content-Type': 'application/json'}})
        
        # Insert or update in database
        db = get_db(env)
        stmt = db.prepare('''
            INSERT INTO prs (pr_url, repo_owner, repo_name, pr_number, title, state, 
                           is_merged, mergeable_state, files_changed, author_login, 
                           author_avatar, checks_passed, checks_failed, checks_skipped, 
                           review_status, last_updated_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(pr_url) DO UPDATE SET
                title = excluded.title,
                state = excluded.state,
                is_merged = excluded.is_merged,
                mergeable_state = excluded.mergeable_state,
                files_changed = excluded.files_changed,
                checks_passed = excluded.checks_passed,
                checks_failed = excluded.checks_failed,
                checks_skipped = excluded.checks_skipped,
                review_status = excluded.review_status,
                last_updated_at = excluded.last_updated_at,
                updated_at = CURRENT_TIMESTAMP
        ''').bind(
            pr_url,
            parsed['owner'],
            parsed['repo'],
            parsed['pr_number'],
            pr_data['title'],
            pr_data['state'],
            pr_data['is_merged'],
            pr_data['mergeable_state'],
            pr_data['files_changed'],
            pr_data['author_login'],
            pr_data['author_avatar'],
            pr_data['checks_passed'],
            pr_data['checks_failed'],
            pr_data['checks_skipped'],
            pr_data['review_status'],
            pr_data['last_updated_at']
        )
        
        await stmt.run()
        
        # Get the PR ID for history recording
        get_id_stmt = db.prepare('SELECT id FROM prs WHERE pr_url = ?').bind(pr_url)
        id_result = await get_id_stmt.first()
        if id_result:
            pr_id = id_result.to_py()['id']
            # Record in history that this PR was added
            await record_pr_history(
                db, 
                pr_id, 
                'added', 
                None,  # No specific actor for adding
                f"PR #{parsed['pr_number']} added to tracker"
            )
        
        return Response.new(json.dumps({'success': True, 'data': pr_data}), 
                          {'headers': {'Content-Type': 'application/json'}})
    except Exception as e:
        return Response.new(json.dumps({'error': f"{type(e).__name__}: {str(e)}"}), 
                          {'status': 500, 'headers': {'Content-Type': 'application/json'}})

async def handle_list_prs(env, repo_filter=None):
    """List all PRs, optionally filtered by repo"""
    try:
        db = get_db(env)
        if repo_filter:
            parts = repo_filter.split('/')
            if len(parts) == 2:
                stmt = db.prepare('''
                    SELECT * FROM prs 
                    WHERE repo_owner = ? AND repo_name = ?
                    ORDER BY last_updated_at DESC
                ''').bind(parts[0], parts[1])
            else:
                stmt = db.prepare('SELECT * FROM prs ORDER BY last_updated_at DESC')
        else:
            stmt = db.prepare('SELECT * FROM prs ORDER BY last_updated_at DESC')
        
        result = await stmt.all()
        # Convert JS Array to Python list
        prs = result.results.to_py() if hasattr(result, 'results') else []
        
        return Response.new(json.dumps({'prs': prs}), 
                          {'headers': {'Content-Type': 'application/json'}})
    except Exception as e:
        return Response.new(json.dumps({'error': f"{type(e).__name__}: {str(e)}"}), 
                          {'status': 500, 'headers': {'Content-Type': 'application/json'}})

async def handle_list_repos(env):
    """List all unique repos"""
    try:
        db = get_db(env)
        stmt = db.prepare('''
            SELECT DISTINCT repo_owner, repo_name, 
                   COUNT(*) as pr_count
            FROM prs 
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
    """Refresh a specific PR's data - requires authentication"""
    try:
        # Verify authentication
        github_username = verify_auth_token(request)
        if not github_username:
            return Response.new(json.dumps({'error': 'Authentication required. Please log in with GitHub to refresh PRs.'}), 
                              {'status': 401, 'headers': {'Content-Type': 'application/json'}})
        
        data = (await request.json()).to_py()
        pr_id = data.get('pr_id')
        
        if not pr_id:
            return Response.new(json.dumps({'error': 'PR ID is required'}), 
                              {'status': 400, 'headers': {'Content-Type': 'application/json'}})
        
        # Get PR data from database (current state before refresh)
        db = get_db(env)
        stmt = db.prepare('SELECT * FROM prs WHERE id = ?').bind(pr_id)
        result = await stmt.first()
        
        if not result:
            return Response.new(json.dumps({'error': 'PR not found'}), 
                              {'status': 404, 'headers': {'Content-Type': 'application/json'}})
        
        # Convert JsProxy to Python dict to make it subscriptable
        old_pr = result.to_py()
        
        # Fetch fresh data from GitHub
        pr_data = await fetch_pr_data(old_pr['repo_owner'], old_pr['repo_name'], old_pr['pr_number'])
        if not pr_data:
            return Response.new(json.dumps({'error': 'Failed to fetch PR data from GitHub'}), 
                              {'status': 500, 'headers': {'Content-Type': 'application/json'}})
        
        # Generate timestamps in Python for consistency and testability
        # Using ISO-8601 format with 'Z' suffix for cross-browser compatibility
        current_timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        
        # Detect changes and prepare history entries
        changes = []
        
        # State changes
        if old_pr.get('state') != pr_data['state']:
            changes.append({
                'type': 'state_change',
                'description': f"State changed from {old_pr.get('state', 'unknown')} to {pr_data['state']}",
                'before': json.dumps({'state': old_pr.get('state')}),
                'after': json.dumps({'state': pr_data['state']})
            })
        
        # Merged status changes
        if old_pr.get('is_merged') != pr_data['is_merged']:
            changes.append({
                'type': 'state_change',
                'description': 'PR was merged' if pr_data['is_merged'] else 'PR merge status changed',
                'before': json.dumps({'is_merged': old_pr.get('is_merged')}),
                'after': json.dumps({'is_merged': pr_data['is_merged']})
            })
        
        # Review status changes
        if old_pr.get('review_status') != pr_data['review_status']:
            changes.append({
                'type': 'review_change',
                'description': f"Review status changed to {pr_data['review_status']}",
                'before': json.dumps({'review_status': old_pr.get('review_status')}),
                'after': json.dumps({'review_status': pr_data['review_status']})
            })
        
        # Check status changes
        if (old_pr.get('checks_passed') != pr_data['checks_passed'] or 
            old_pr.get('checks_failed') != pr_data['checks_failed'] or 
            old_pr.get('checks_skipped') != pr_data['checks_skipped']):
            changes.append({
                'type': 'checks_change',
                'description': f"Checks: {pr_data['checks_passed']} passed, {pr_data['checks_failed']} failed, {pr_data['checks_skipped']} skipped",
                'before': json.dumps({
                    'checks_passed': old_pr.get('checks_passed'),
                    'checks_failed': old_pr.get('checks_failed'),
                    'checks_skipped': old_pr.get('checks_skipped')
                }),
                'after': json.dumps({
                    'checks_passed': pr_data['checks_passed'],
                    'checks_failed': pr_data['checks_failed'],
                    'checks_skipped': pr_data['checks_skipped']
                })
            })
        
        # Update database
        update_stmt = db.prepare('''
            UPDATE prs SET
                title = ?, state = ?, is_merged = ?, mergeable_state = ?,
                files_changed = ?, checks_passed = ?, checks_failed = ?,
                checks_skipped = ?, review_status = ?, last_updated_at = ?,
                last_refreshed_at = ?,
                updated_at = ?
            WHERE id = ?
        ''').bind(
            pr_data['title'],
            pr_data['state'],
            pr_data['is_merged'],
            pr_data['mergeable_state'],
            pr_data['files_changed'],
            pr_data['checks_passed'],
            pr_data['checks_failed'],
            pr_data['checks_skipped'],
            pr_data['review_status'],
            pr_data['last_updated_at'],
            current_timestamp,
            current_timestamp,
            pr_id
        )
        
        await update_stmt.run()
        
        # Record refresh action in history
        await record_pr_history(
            db,
            pr_id,
            'refresh',
            github_username,
            f"PR refreshed by {github_username}"
        )
        
        # Record any detected changes
        for change in changes:
            await record_pr_history(
                db,
                pr_id,
                change['type'],
                None,  # Changes are system-detected, not user-initiated
                change['description'],
                change.get('before'),
                change.get('after')
            )
        
        # Get refresh count (count 'refresh' action types)
        count_stmt = db.prepare("SELECT COUNT(*) as count FROM pr_history WHERE pr_id = ? AND action_type = 'refresh'").bind(pr_id)
        count_result = await count_stmt.first()
        refresh_count = count_result.to_py()['count'] if count_result else 0
        
        return Response.new(json.dumps({
            'success': True, 
            'data': pr_data,
            'refresh_count': refresh_count,
            'refreshed_by': github_username,
            'changes_detected': len(changes)
        }), 
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
        
        headers = {
            'User-Agent': 'PR-Tracker/1.0',
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28'
        }
        
        # Fetch rate limit from GitHub API
        rate_limit_url = "https://api.github.com/rate_limit"
        response = await fetch_with_headers(rate_limit_url, headers)
        
        if response.status != 200:
            error_msg = await response.text()
            return Response.new(
                json.dumps({
                    'error': f'GitHub API Error: {response.status}',
                    'details': error_msg
                }), 
                {'status': response.status, 'headers': {'Content-Type': 'application/json'}}
            )
        
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
            {'headers': {
                'Content-Type': 'application/json',
                'Cache-Control': f'public, max-age={_RATE_LIMIT_CACHE_TTL}'
            }}
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
        }), 
                          {'headers': {'Content-Type': 'application/json'}})
    except Exception as e:
        # Database not configured
        return Response.new(json.dumps({
            'database_configured': False,
            'error': str(e),
            'environment': getattr(env, 'ENVIRONMENT', 'unknown')
        }), 
                          {'headers': {'Content-Type': 'application/json'}})

async def handle_get_pr_history(env, pr_id):
    """Get full history for a specific PR"""
    try:
        db = get_db(env)
        
        # Get full history from pr_history table
        stmt = db.prepare('''
            SELECT action_type, actor, description, before_state, after_state, created_at
            FROM pr_history
            WHERE pr_id = ?
            ORDER BY created_at DESC
        ''').bind(pr_id)
        
        result = await stmt.all()
        history = result.results.to_py() if hasattr(result, 'results') else []
        
        # Get refresh count (count only 'refresh' actions)
        count_stmt = db.prepare("SELECT COUNT(*) as count FROM pr_history WHERE pr_id = ? AND action_type = 'refresh'").bind(pr_id)
        count_result = await count_stmt.first()
        refresh_count = count_result.to_py()['count'] if count_result else 0
        
        # Get unique user count (count distinct actors for refresh actions)
        unique_stmt = db.prepare("SELECT COUNT(DISTINCT actor) as count FROM pr_history WHERE pr_id = ? AND action_type = 'refresh' AND actor IS NOT NULL").bind(pr_id)
        unique_result = await unique_stmt.first()
        unique_users = unique_result.to_py()['count'] if unique_result else 0
        
        return Response.new(json.dumps({
            'refresh_count': refresh_count,
            'unique_users': unique_users,
            'history': history
        }), 
                          {'headers': {'Content-Type': 'application/json'}})
    except Exception as e:
        return Response.new(json.dumps({'error': f"{type(e).__name__}: {str(e)}"}), 
                          {'status': 500, 'headers': {'Content-Type': 'application/json'}})


async def on_fetch(request, env):
    """Main request handler"""
    url = URL.new(request.url)
    path = url.pathname
    
    # Strip /leaf prefix
    if path == '/leaf':
        path = '/'
    elif path.startswith('/leaf/'):
        path = path[5:]  # Remove '/leaf' (5 characters)
    
    # CORS headers
    # NOTE: '*' allows all origins for public access. In production, consider
    # restricting to specific domains by setting this to your domain(s).
    cors_headers = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
    }
    
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        return Response.new('', {'headers': cors_headers})
    
    # Serve HTML for root path  
    if path == '/' or path == '/index.html':
        # Use env.ASSETS to serve static files if available
        if hasattr(env, 'ASSETS'):
            return await env.ASSETS.fetch(request)
        else:
            # Fallback: return simple message
            return Response.new('Please configure assets in wrangler.toml', 
                              {'status': 200, 'headers': {**cors_headers, 'Content-Type': 'text/html'}})
    
    # Initialize database schema on first API request (idempotent, safe to call multiple times)
    if path.startswith('/api/'):
        await init_database_schema(env)
    
    # API endpoints
    if path == '/api/prs' and request.method == 'GET':
        repo_filter = url.searchParams.get('repo')
        response = await handle_list_prs(env, repo_filter)
        for key, value in cors_headers.items():
            response.headers.set(key, value)
        return response
    
    if path == '/api/prs' and request.method == 'POST':
        response = await handle_add_pr(request, env)
        for key, value in cors_headers.items():
            response.headers.set(key, value)
        return response
    
    if path == '/api/repos' and request.method == 'GET':
        response = await handle_list_repos(env)
        for key, value in cors_headers.items():
            response.headers.set(key, value)
        return response
    
    if path == '/api/refresh' and request.method == 'POST':
        response = await handle_refresh_pr(request, env)
        for key, value in cors_headers.items():
            response.headers.set(key, value)
        return response
    
    if path == '/api/rate-limit' and request.method == 'GET':
        response = await handle_rate_limit(env)
        for key, value in cors_headers.items():
            response.headers.set(key, value)
        return response
    
    if path == '/api/status' and request.method == 'GET':
        response = await handle_status(env)
        for key, value in cors_headers.items():
            response.headers.set(key, value)
        return response
    
    if path.startswith('/api/pr-history/') and request.method == 'GET':
        # Extract PR ID from path like /api/pr-history/123
        pr_id = path.split('/')[-1]
        try:
            pr_id = int(pr_id)
            response = await handle_get_pr_history(env, pr_id)
            for key, value in cors_headers.items():
                response.headers.set(key, value)
            return response
        except ValueError:
            return Response.new(json.dumps({'error': 'Invalid PR ID'}), 
                              {'status': 400, 'headers': {**cors_headers, 'Content-Type': 'application/json'}})
    
    # Legacy endpoint for backward compatibility
    if path.startswith('/api/refresh-history/') and request.method == 'GET':
        # Redirect to new endpoint
        pr_id = path.split('/')[-1]
        try:
            pr_id = int(pr_id)
            response = await handle_get_pr_history(env, pr_id)
            for key, value in cors_headers.items():
                response.headers.set(key, value)
            return response
        except ValueError:
            return Response.new(json.dumps({'error': 'Invalid PR ID'}), 
                              {'status': 400, 'headers': {**cors_headers, 'Content-Type': 'application/json'}})
    
    # Try to serve from assets
    if hasattr(env, 'ASSETS'):
        return await env.ASSETS.fetch(request)
    
    # 404
    return Response.new('Not Found', {'status': 404, 'headers': cors_headers})
