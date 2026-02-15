"""
Shared utility functions for URL parsing.
This module has no dependencies on Cloudflare Workers APIs and can be used
by both the production code (index.py) and tests.
"""
import re


def parse_pr_url(pr_url):
    """
    Parse GitHub PR URL to extract owner, repo, and PR number.
    
    Security Hardening (Issue #45):
    - Type validation to prevent type confusion attacks
    - Anchored regex pattern to block malformed URLs with trailing junk
    - Raises ValueError instead of returning None for better error handling
    
    Args:
        pr_url: GitHub PR URL string
        
    Returns:
        dict with owner, repo, and pr_number keys if valid
        
    Raises:
        ValueError: If URL is invalid or not a string
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
