"""
Helper functions extracted for testing.
These functions have no dependencies on Cloudflare Workers APIs.

Note: These functions are duplicated from src/index.py for testing purposes.
The main application (index.py) keeps its own copies since it runs in a 
Cloudflare Workers environment which may have import restrictions.
"""
import re


def parse_pr_url(pr_url):
    """Parse GitHub PR URL to extract owner, repo, and PR number
    
    Args:
        pr_url: GitHub PR URL string
        
    Returns:
        dict with owner, repo, and pr_number keys if valid, None otherwise
    """
    pattern = r'https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)'
    match = re.match(pattern, pr_url)
    if match:
        return {
            'owner': match.group(1),
            'repo': match.group(2),
            'pr_number': int(match.group(3))
        }
    return None
