"""Main entry point for BLT-Leaf PR Readiness Checker - Cloudflare Worker"""

import json
import re
import time as _time

from js import Headers, Object, Response, URL
from pyodide.ffi import to_js

from slack_notifier import notify_slack_error, notify_slack_exception

# Import all handlers
from handlers import (
    handle_add_pr,
    handle_batch_refresh_prs,
    handle_get_pr,
    handle_github_webhook,
    handle_list_authors,
    handle_list_prs,
    handle_list_repos,
    handle_pr_readiness,
    handle_pr_review_analysis,
    handle_pr_timeline,
    handle_pr_updates_check,
    handle_rate_limit,
    handle_refresh_org,
    handle_refresh_pr,
    handle_scheduled_refresh,
    handle_status,
)
from auth_handlers import (
    handle_auth_callback,
    handle_auth_login,
    handle_auth_logout,
    handle_auth_user,
)

# Matches fingerprinted asset filenames produced by scripts/fingerprint.js.
# Pattern: <stem>.<8 hex chars>.<ext> e.g. error-reporter.abc12345.js
_FINGERPRINTED_RE = re.compile(r"\.[0-9a-f]{8}\.(js|css)$")

_err_rl: dict = {}
_err_dedup: dict = {}
_slack_bgt: dict = {"count": 0, "window_start": 0.0}


def is_local_dev_request(request):
    """Detect local wrangler dev traffic."""
    request_url = str(request.url)
    return "127.0.0.1" in request_url or "localhost" in request_url


def is_cache_controlled_static_path(path):
    """Static asset paths that should get explicit cache-control headers."""
    if path == "/" or path == "/sw.js":
        return True
    return path.endswith(".js") or path.endswith(".css") or path.endswith(".html")


async def fetch_static_asset_with_cache_headers(request, env, path):
    """Fetch static assets and enforce cache behavior by asset type."""
    asset_response = await env.ASSETS.fetch(request)
    if not is_cache_controlled_static_path(path):
        return asset_response

    headers = Headers.new(asset_response.headers)
    if is_local_dev_request(request):
        headers.set("Cache-Control", "no-store")
    elif path == "/" or path == "/sw.js" or path.endswith(".html"):
        headers.set("Cache-Control", "no-cache, must-revalidate")
    elif _FINGERPRINTED_RE.search(path):
        headers.set("Cache-Control", "public, max-age=31536000, immutable")
    else:
        headers.set("Cache-Control", "no-cache, must-revalidate")

    return Response.new(
        asset_response.body,
        {
            "status": asset_response.status,
            "statusText": asset_response.statusText,
            "headers": headers,
        },
    )


def check_rate_limit_bucket(bucket, ip, limit, window):
    now = _time.time()
    key = f"{bucket}:{ip}"
    entry = _err_rl.get(key)
    if not entry or (now - entry["window_start"]) >= window:
        _err_rl[key] = {"count": 1, "window_start": now}
        return True, 0
    if entry["count"] < limit:
        entry["count"] += 1
        return True, 0
    return False, int(window - (now - entry["window_start"])) + 1


def should_send_dedupe(sig, ttl):
    now = _time.time()
    if _err_dedup.get(sig, 0) > now:
        return False
    _err_dedup[sig] = now + ttl
    return True


def slack_budget_allow(limit, window):
    now = _time.time()
    window_start = _slack_bgt["window_start"]
    if not window_start or (now - window_start) >= window:
        _slack_bgt.update({"count": 1, "window_start": now})
        return True, 0
    if _slack_bgt["count"] < limit:
        _slack_bgt["count"] += 1
        return True, 0
    return False, int(window - (now - window_start)) + 1


def _get_client_ip(request):
    return (
        request.headers.get("cf-connecting-ip")
        or (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        or request.headers.get("x-real-ip")
        or "unknown"
    )


def json_response(data: dict, status: int, extra_headers: dict | None = None):
    headers = {"Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)

    init = to_js(
        {"status": status, "headers": headers},
        dict_converter=Object.fromEntries,
    )
    return Response.new(json.dumps(data), init)


async def on_fetch(request, env):
    """Main request handler."""
    slack_webhook = getattr(env, "SLACK_ERROR_WEBHOOK", "")

    url = URL.new(request.url)
    path = url.pathname

    if path == "/leaf":
        path = "/"
    elif path.startswith("/leaf/"):
        path = path[5:]

    cors_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, x-github-token",
    }

    try:
        if request.method == "OPTIONS":
            return Response.new("", {"headers": cors_headers})

        if path == "/" or path == "/index.html":
            if hasattr(env, "ASSETS"):
                return await fetch_static_asset_with_cache_headers(request, env, path)
            return Response.new(
                "Please configure assets in wrangler.toml",
                {"status": 200, "headers": {**cors_headers, "Content-Type": "text/html"}},
            )

        response = None

        if path == "/api/prs/updates" and request.method == "GET":
            response = await handle_pr_updates_check(env)
        elif path == "/api/prs":
            if request.method == "GET":
                repo = url.searchParams.get("repo")
                org = url.searchParams.get("org")
                author = url.searchParams.get("author")
                page = url.searchParams.get("page")
                per_page_param = url.searchParams.get("per_page")
                sort_by = url.searchParams.get("sort_by")
                sort_dir = url.searchParams.get("sort_dir")

                per_page = 30
                if per_page_param:
                    try:
                        per_page = int(per_page_param)
                        if per_page < 10:
                            per_page = 10
                        elif per_page > 1000:
                            per_page = 1000
                    except (ValueError, TypeError):
                        per_page = 30

                response = await handle_list_prs(
                    env,
                    repo,
                    page if page else 1,
                    per_page,
                    sort_by,
                    sort_dir,
                    org,
                    author,
                )
            elif request.method == "POST":
                response = await handle_add_pr(request, env)
        elif path.startswith("/api/prs/") and "/" not in path[len("/api/prs/"):] and request.method == "GET":
            pr_id_str = path[len("/api/prs/"):]
            if pr_id_str.isdigit():
                response = await handle_get_pr(env, int(pr_id_str))
        elif path == "/api/repos" and request.method == "GET":
            response = await handle_list_repos(env)
        elif path == "/api/authors" and request.method == "GET":
            response = await handle_list_authors(env)
        elif path == "/api/refresh" and request.method == "POST":
            response = await handle_refresh_pr(request, env)
        elif path == "/api/refresh-batch" and request.method == "POST":
            response = await handle_batch_refresh_prs(request, env)
        elif path == "/api/refresh-org" and request.method == "POST":
            response = await handle_refresh_org(request, env)
        elif path == "/api/rate-limit" and request.method == "GET":
            response = await handle_rate_limit(request, env)
            for key, value in cors_headers.items():
                response.headers.set(key, value)
            return response
        elif path == "/api/auth/login" and request.method == "GET":
            response = await handle_auth_login(request, env)
            for key, value in cors_headers.items():
                response.headers.set(key, value)
            return response
        elif path == "/api/auth/callback" and request.method == "GET":
            response = await handle_auth_callback(request, env)
            for key, value in cors_headers.items():
                response.headers.set(key, value)
            return response
        elif path == "/api/auth/user" and request.method == "GET":
            response = await handle_auth_user(request, env)
            for key, value in cors_headers.items():
                response.headers.set(key, value)
            return response
        elif path == "/api/auth/logout" and request.method == "POST":
            response = await handle_auth_logout(request, env)
            for key, value in cors_headers.items():
                response.headers.set(key, value)
            return response
        elif path == "/api/status" and request.method == "GET":
            response = await handle_status(env)
        elif path == "/api/github/webhook" and request.method == "POST":
            response = await handle_github_webhook(request, env)
            for key, value in cors_headers.items():
                response.headers.set(key, value)
            return response
        elif path == "/api/test-error" and request.method == "POST":
            raise RuntimeError("Slack test error triggered intentionally from /api/test-error")
        elif path == "/api/error-test" and request.method == "POST":
            ip = _get_client_ip(request)

            limit = int(getattr(env, "ERROR_TEST_RATE_LIMIT", 1) or 1)
            window = int(getattr(env, "ERROR_TEST_RATE_WINDOW", 60) or 60)
            allowed, retry_after = check_rate_limit_bucket("error-test", ip, limit, window)
            if not allowed:
                response = json_response(
                    {"ok": False, "reason": "Rate limit exceeded"},
                    429,
                    extra_headers={"Retry-After": str(retry_after)},
                )
                for key, value in cors_headers.items():
                    response.headers.set(key, value)
                return response

            slack_webhook = (getattr(env, "SLACK_ERROR_WEBHOOK", "") or "").strip()
            if not slack_webhook:
                response = json_response({"ok": False, "reason": "SLACK_ERROR_WEBHOOK not set"}, 500)
                for key, value in cors_headers.items():
                    response.headers.set(key, value)
                return response

            slack_ok = await notify_slack_error(
                slack_webhook,
                error_type="ErrorTest",
                error_message="Slack error-test triggered",
                context={"source": "/api/error-test", "url": str(request.url), "ip": ip},
                stack_trace=None,
            )
            if slack_ok:
                response = json_response({"ok": True, "sent_to_slack": True}, 200)
            else:
                print("Error-test Slack send failed")
                response = json_response({"ok": False, "reason": "Slack send failed (check worker logs)"}, 502)

            for key, value in cors_headers.items():
                response.headers.set(key, value)
            return response
        elif path == "/api/client-error" and request.method == "POST":
            ip = _get_client_ip(request)

            limit = int(getattr(env, "CLIENT_ERROR_RATE_LIMIT", 5) or 5)
            window = int(getattr(env, "CLIENT_ERROR_RATE_WINDOW", 60) or 60)
            allowed, retry_after = check_rate_limit_bucket("client-error", ip, limit, window)
            if not allowed:
                response = json_response(
                    {"error": "Rate limit exceeded"},
                    429,
                    extra_headers={"Retry-After": str(retry_after)},
                )
                for key, value in cors_headers.items():
                    response.headers.set(key, value)
                return response

            max_bytes = int(getattr(env, "CLIENT_ERROR_MAX_BYTES", 8192) or 8192)
            try:
                content_len = int(request.headers.get("content-length") or "0")
            except Exception:
                content_len = 0
            if content_len and content_len > max_bytes:
                response = json_response({"error": "Payload too large"}, 413)
                for key, value in cors_headers.items():
                    response.headers.set(key, value)
                return response

            body = {}
            try:
                body = (await request.json()).to_py()
            except Exception:
                try:
                    text = await request.text()
                    body = json.loads(text) if text else {}
                except Exception:
                    body = {}

            error_type = str(body.get("error_type", "FrontendError"))[:80]
            error_message = str(body.get("message", "Unknown frontend error"))[:300]
            stack_trace = str(body.get("stack", ""))[:2000] or None

            url_here = str(body.get("url", ""))[:200] or ""
            line = str(body.get("line", ""))[:20] or ""
            col = str(body.get("col", ""))[:20] or ""
            resource = str(body.get("resource", ""))[:200] or ""

            dedupe_ttl = int(getattr(env, "CLIENT_ERROR_DEDUPE_TTL", 300) or 300)
            signature = f"{error_type}|{error_message}|{url_here}|{line}|{col}|{resource}"
            should_slack = should_send_dedupe(signature, dedupe_ttl)

            slack_cap = int(getattr(env, "SLACK_MAX_PER_MIN", 20) or 20)
            slack_allowed, slack_retry = slack_budget_allow(slack_cap, 60)

            ctx = {key: str(value)[:200] for key, value in body.items() if key not in ("error_type", "message", "stack")}
            ctx["source"] = "frontend"
            ctx["ip"] = ip
            ctx["dedupe"] = "1" if should_slack else "0"

            slack_sent = False
            if should_slack and slack_allowed:
                slack_sent = await notify_slack_error(
                    slack_webhook,
                    error_type=error_type,
                    error_message=error_message,
                    context=ctx,
                    stack_trace=stack_trace,
                )
                if not slack_sent:
                    print("Slack: failed to report frontend error")
            else:
                if not should_slack:
                    print("Slack: deduped client-error")
                elif not slack_allowed:
                    print(f"Slack: global cap reached, retry after {slack_retry}s")

            response = json_response(
                {"ok": True, "slack_sent": slack_sent, "deduped": not should_slack},
                200,
            )
            for key, value in cors_headers.items():
                response.headers.set(key, value)
            return response
        elif path.startswith("/api/prs/") and path.endswith("/timeline") and request.method == "GET":
            response = await handle_pr_timeline(request, env, path)
            for key, value in cors_headers.items():
                response.headers.set(key, value)
            return response
        elif path.startswith("/api/prs/") and path.endswith("/review-analysis") and request.method == "GET":
            response = await handle_pr_review_analysis(request, env, path)
            for key, value in cors_headers.items():
                response.headers.set(key, value)
            return response
        elif path.startswith("/api/prs/") and path.endswith("/readiness") and request.method == "GET":
            response = await handle_pr_readiness(request, env, path)
            for key, value in cors_headers.items():
                response.headers.set(key, value)
            return response

        if response is None:
            if hasattr(env, "ASSETS"):
                return await fetch_static_asset_with_cache_headers(request, env, path)
            return Response.new("Not Found", {"status": 404, "headers": cors_headers})

        for key, value in cors_headers.items():
            if response:
                response.headers.set(key, value)
        return response

    except Exception as exc:
        try:
            await notify_slack_exception(
                slack_webhook,
                exc,
                context={
                    "path": path,
                    "method": str(request.method),
                },
            )
        except Exception as slack_err:
            print(f"Slack: failed to report exception: {slack_err}")
        return Response.new(
            '{"error": "Internal server error"}',
            {"status": 500, "headers": {**cors_headers, "Content-Type": "application/json"}},
        )


async def on_scheduled(controller, env, ctx):
    """Cloudflare Cron Trigger handler - runs every hour."""
    slack_webhook = getattr(env, "SLACK_ERROR_WEBHOOK", "")
    try:
        await handle_scheduled_refresh(env)
    except Exception as exc:
        try:
            await notify_slack_exception(
                slack_webhook,
                exc,
                context={
                    "handler": "on_scheduled",
                },
            )
        except Exception as slack_err:
            print(f"Slack: failed to report scheduled exception: {slack_err}")
        raise
