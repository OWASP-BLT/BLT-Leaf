"""
Utility functions for URL parsing and timestamp handling
"""
import re
from datetime import datetime


def parse_pr_url(pr_url):
    """
    Parse GitHub PR URL to extract owner, repo, and PR number.
    
    Security Hardening (Issue #45):
    - Type validation to prevent type confusion attacks
    - Anchored regex pattern to block malformed URLs with trailing junk
    - Raises ValueError instead of returning None for better error handling
    """
    # FIX Issue #45: Type validation
    if not isinstance(pr_url, str):
        raise ValueError("PR URL must be a string")
    
    if not pr_url:
        raise ValueError("PR URL is required")
    
    pr_url = pr_url.strip().rstrip('/')
    
    # FIX Issue #45: Anchored regex - must match EXACTLY, no trailing junk allowed
    pattern = r'^https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)$'
    match = re.match(pattern, pr_url)
    
    if not match:
        # FIX Issue #45: Raise error instead of returning None
        raise ValueError("Invalid GitHub PR URL. Format: https://github.com/OWNER/REPO/pull/NUMBER")
    
    return {
        'owner': match.group(1),
        'repo': match.group(2),
        'pr_number': int(match.group(3))
    }


def parse_repo_url(url):
    """Parse GitHub Repo URL to extract owner and repo name"""
    if not url: return None
    url = url.strip().rstrip('/')
    pattern = r'https?://github\.com/([^/]+)/([^/]+)(?:/.*)?$'
    match = re.match(pattern, url)
    if match:
        return {
            'owner': match.group(1),
            'repo': match.group(2)
        }
    return None


def parse_github_timestamp(timestamp_str):
    """Parse GitHub ISO 8601 timestamp to datetime object"""
    try:
        # GitHub timestamps are in format: 2024-01-15T10:30:45Z
        return datetime.strptime(timestamp_str.replace('Z', '+00:00'), '%Y-%m-%dT%H:%M:%S%z')
    except Exception as exc:
        # Raise error instead of silently using current time to avoid incorrect event ordering
        raise ValueError(f"Invalid GitHub timestamp: {timestamp_str!r}") from exc
