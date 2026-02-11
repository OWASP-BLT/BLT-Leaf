from js import Response, fetch, Headers, URL, Object, Date
from pyodide.ffi import to_js
import json
import re
from datetime import datetime, timezone

# Track if schema initialization has been attempted
_schema_init_attempted = False

# In-memory cache for rate limit data
_rate_limit_cache = {
    'data': None,
    'timestamp': 0
}
_RATE_LIMIT_CACHE_TTL = 300

def parse_pr_url(pr_url):
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
    for name in ['DB', 'pr_tracker']:
        if hasattr(env, name):
            return getattr(env, name)
    raise Exception("Database binding 'DB' not found. Check wrangler.toml")

async def init_database_schema(env):
    global _schema_init_attempted
    if _schema_init_attempted:
        return
    _schema_init_attempted = True
    try:
        db = get_db(env)
        await db.prepare('''
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
        ''').run()
    except Exception as e:
        print(f"Schema Init Note: {str(e)}")

async def fetch_with_headers(url, headers=None):
    if headers:
        options = to_js({
            "method": "GET",
            "headers": headers
        }, dict_converter=Object.fromEntries)
        return await fetch(url, options)
    return await fetch(url)

async def fetch_pr_data(owner, repo, pr_number, env):
    """Fetch PR data with Authentication"""
    github_token = getattr(env, "GITHUB_TOKEN", None)
    headers = {
        'User-Agent': 'PR-Tracker/1.0',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28'
    }
    if github_token:
        headers['Authorization'] = f'Bearer {github_token}'
        
    pr_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
    pr_response = await fetch_with_headers(pr_url, headers)
    
    if pr_response.status >= 400:
        error_text = await pr_response.text()
        raise Exception(f"GitHub Error {pr_response.status}: {error_text}")

    pr_data = (await pr_response.json()).to_py()
    
    # Fetch Checks
    checks_url = f"https://api.github.com/repos/{owner}/{repo}/commits/{pr_data['head']['sha']}/check-runs"
    checks_res = await fetch_with_headers(checks_url, headers)
    checks_data = (await checks_res.json()).to_py() if checks_res.status == 200 else {}

    passed = sum(1 for c in checks_data.get('check_runs', []) if c['conclusion'] == 'success')
    failed = sum(1 for c in checks_data.get('check_runs', []) if c['conclusion'] in ['failure', 'timed_out'])

    return {
        'title': pr_data.get('title', ''),
        'state': pr_data.get('state', ''),
        'is_merged': 1 if pr_data.get('merged', False) else 0,
        'mergeable_state': pr_data.get('mergeable_state', ''),
        'files_changed': pr_data.get('changed_files', 0),
        'author_login': pr_data['user']['login'],
        'author_avatar': pr_data['user']['avatar_url'],
        'checks_passed': passed,
        'checks_failed': failed,
        'checks_skipped': 0,
        'review_status': 'pending',
        'last_updated_at': pr_data.get('updated_at', '')
    }

async def handle_rate_limit(env):
    """Authenticated rate limit check"""
    github_token = getattr(env, "GITHUB_TOKEN", None)
    headers = {'User-Agent': 'PR-Tracker/1.0'}
    if github_token:
        headers['Authorization'] = f'Bearer {github_token}'
    
    res = await fetch_with_headers("https://api.github.com/rate_limit", headers)
    data = (await res.json()).to_py()
    core = data.get('resources', {}).get('core', {})
    return Response.new(json.dumps(core), {'headers': {'Content-Type': 'application/json'}})

async def handle_add_pr(request, env):
    data = (await request.json()).to_py()
    parsed = parse_pr_url(data.get('pr_url', ''))
    if not parsed:
        return Response.new(json.dumps({'error': 'Invalid URL'}), {'status': 400})
    
    pr_data = await fetch_pr_data(parsed['owner'], parsed['repo'], parsed['pr_number'], env)
    db = get_db(env)
    await db.prepare('''
        INSERT INTO prs (pr_url, repo_owner, repo_name, pr_number, title, state, author_login, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(pr_url) DO UPDATE SET title=excluded.title, state=excluded.state
    ''').bind(data['pr_url'], parsed['owner'], parsed['repo'], parsed['pr_number'], pr_data['title'], pr_data['state'], pr_data['author_login']).run()
    
    return Response.new(json.dumps({'success': True}), {'headers': {'Content-Type': 'application/json'}})

async def on_fetch(request, env):
    url = URL.new(request.url)
    path = url.pathname
    cors_headers = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
    }

    if request.method == 'OPTIONS':
        return Response.new('', {'headers': cors_headers})

    if path.startswith('/api/'):
        await init_database_schema(env)

    response = None
    if path == '/api/rate-limit':
        response = await handle_rate_limit(env)
    elif path == '/api/prs' and request.method == 'POST':
        response = await handle_add_pr(request, env)
    elif path == '/api/prs' and request.method == 'GET':
        db = get_db(env)
        result = await db.prepare('SELECT * FROM prs').all()
        response = Response.new(json.dumps({'prs': result.results.to_py()}), {'headers': {'Content-Type': 'application/json'}})

    if response:
        for k, v in cors_headers.items():
            response.headers.set(k, v)
        return response

    if hasattr(env, 'ASSETS'):
        return await env.ASSETS.fetch(request)
    
    return Response.new('Not Found', {'status': 404})
