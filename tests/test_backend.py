"""
Unit tests for backend Python functions in BLT-Leaf
"""
import unittest
import sys
import os

# Add src to path to import the module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Import from helpers module which has no Cloudflare dependencies
from helpers import parse_pr_url


class TestParsePRUrl(unittest.TestCase):
    """Test the parse_pr_url function"""
    
    def test_valid_https_url(self):
        """Test parsing a valid HTTPS GitHub PR URL"""
        url = "https://github.com/OWASP-BLT/BLT-Leaf/pull/123"
        result = parse_pr_url(url)
        
        self.assertIsNotNone(result)
        self.assertEqual(result['owner'], 'OWASP-BLT')
        self.assertEqual(result['repo'], 'BLT-Leaf')
        self.assertEqual(result['pr_number'], 123)
    
    def test_valid_http_url(self):
        """Test parsing a valid HTTP GitHub PR URL"""
        url = "http://github.com/microsoft/vscode/pull/456"
        result = parse_pr_url(url)
        
        self.assertIsNotNone(result)
        self.assertEqual(result['owner'], 'microsoft')
        self.assertEqual(result['repo'], 'vscode')
        self.assertEqual(result['pr_number'], 456)
    
    def test_url_with_trailing_slash(self):
        """Test parsing URL with trailing slash"""
        url = "https://github.com/facebook/react/pull/789/"
        result = parse_pr_url(url)
        
        # re.match() matches from the start and the regex doesn't require end-of-string
        # so it successfully matches the URL up to the PR number, ignoring the trailing slash
        self.assertIsNotNone(result)
        self.assertEqual(result['owner'], 'facebook')
        self.assertEqual(result['repo'], 'react')
        self.assertEqual(result['pr_number'], 789)
    
    def test_invalid_url_format(self):
        """Test parsing an invalid URL format"""
        urls = [
            "https://github.com/owner/repo/issues/123",  # Issue, not PR
            "https://github.com/owner/repo",  # No PR number
            "https://gitlab.com/owner/repo/pull/123",  # Not GitHub
            "not-a-url",  # Not a URL at all
            "",  # Empty string
        ]
        
        for url in urls:
            result = parse_pr_url(url)
            self.assertIsNone(result, f"Expected None for URL: {url}")
    
    def test_large_pr_number(self):
        """Test parsing URL with a large PR number"""
        url = "https://github.com/owner/repo/pull/999999"
        result = parse_pr_url(url)
        
        self.assertIsNotNone(result)
        self.assertEqual(result['pr_number'], 999999)
    
    def test_special_characters_in_names(self):
        """Test parsing URL with special characters in owner/repo names"""
        # GitHub allows hyphens and underscores in names
        url = "https://github.com/my-org_123/my-repo_456/pull/1"
        result = parse_pr_url(url)
        
        self.assertIsNotNone(result)
        self.assertEqual(result['owner'], 'my-org_123')
        self.assertEqual(result['repo'], 'my-repo_456')





if __name__ == '__main__':
    unittest.main()
