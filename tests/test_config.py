"""
Tests for database schema and configuration files
"""
import unittest
import os


class TestConfiguration(unittest.TestCase):
    """Test configuration files exist and are valid"""
    
    def setUp(self):
        """Set up test - locate project root"""
        self.project_root = os.path.join(os.path.dirname(__file__), '..')
    
    def test_wrangler_toml_exists(self):
        """Test that wrangler.toml exists"""
        wrangler_path = os.path.join(self.project_root, 'wrangler.toml')
        self.assertTrue(os.path.exists(wrangler_path), 
                       "wrangler.toml should exist in project root")
    
    def test_wrangler_toml_contains_name(self):
        """Test that wrangler.toml contains a name field"""
        wrangler_path = os.path.join(self.project_root, 'wrangler.toml')
        with open(wrangler_path, 'r') as f:
            content = f.read()
        self.assertIn('name =', content, 
                     "wrangler.toml should contain 'name' field")
    
    def test_wrangler_toml_contains_python_flag(self):
        """Test that wrangler.toml is configured for Python workers"""
        wrangler_path = os.path.join(self.project_root, 'wrangler.toml')
        with open(wrangler_path, 'r') as f:
            content = f.read()
        self.assertIn('python_workers', content, 
                     "wrangler.toml should have python_workers compatibility flag")
    
    def test_schema_sql_exists(self):
        """Test that schema.sql exists"""
        schema_path = os.path.join(self.project_root, 'schema.sql')
        self.assertTrue(os.path.exists(schema_path), 
                       "schema.sql should exist in project root")
    
    def test_schema_sql_contains_table_definition(self):
        """Test that schema.sql contains table definitions"""
        schema_path = os.path.join(self.project_root, 'schema.sql')
        with open(schema_path, 'r') as f:
            content = f.read()
        self.assertIn('CREATE TABLE', content, 
                     "schema.sql should contain CREATE TABLE statements")
    
    def test_schema_sql_contains_prs_table(self):
        """Test that schema.sql defines the prs table"""
        schema_path = os.path.join(self.project_root, 'schema.sql')
        with open(schema_path, 'r') as f:
            content = f.read()
        self.assertIn('prs', content, 
                     "schema.sql should define prs table")
    
    def test_index_py_exists(self):
        """Test that src/index.py exists"""
        index_path = os.path.join(self.project_root, 'src', 'index.py')
        self.assertTrue(os.path.exists(index_path), 
                       "src/index.py should exist")
    
    def test_index_html_exists(self):
        """Test that public/index.html exists"""
        html_path = os.path.join(self.project_root, 'public', 'index.html')
        self.assertTrue(os.path.exists(html_path), 
                       "public/index.html should exist")
    
    def test_package_json_exists(self):
        """Test that package.json exists"""
        package_path = os.path.join(self.project_root, 'package.json')
        self.assertTrue(os.path.exists(package_path), 
                       "package.json should exist in project root")


class TestSchemaFields(unittest.TestCase):
    """Test that schema.sql contains all required fields"""
    
    def setUp(self):
        """Load schema.sql content"""
        project_root = os.path.join(os.path.dirname(__file__), '..')
        schema_path = os.path.join(project_root, 'schema.sql')
        with open(schema_path, 'r') as f:
            self.schema_content = f.read()
    
    def test_schema_has_id_field(self):
        """Test that prs table has id field"""
        self.assertIn('id INTEGER PRIMARY KEY', self.schema_content)
    
    def test_schema_has_pr_url_field(self):
        """Test that prs table has pr_url field"""
        self.assertIn('pr_url TEXT NOT NULL UNIQUE', self.schema_content)
    
    def test_schema_has_repo_fields(self):
        """Test that prs table has repo_owner and repo_name fields"""
        self.assertIn('repo_owner TEXT NOT NULL', self.schema_content)
        self.assertIn('repo_name TEXT NOT NULL', self.schema_content)
    
    def test_schema_has_pr_number_field(self):
        """Test that prs table has pr_number field"""
        self.assertIn('pr_number INTEGER NOT NULL', self.schema_content)
    
    def test_schema_has_check_fields(self):
        """Test that prs table has check status fields"""
        self.assertIn('checks_passed', self.schema_content)
        self.assertIn('checks_failed', self.schema_content)
        self.assertIn('checks_skipped', self.schema_content)
    
    def test_schema_has_review_status_field(self):
        """Test that prs table has review_status field"""
        self.assertIn('review_status', self.schema_content)
    
    def test_schema_has_indexes(self):
        """Test that schema creates indexes"""
        self.assertIn('CREATE INDEX', self.schema_content)
        self.assertIn('idx_repo', self.schema_content)


if __name__ == '__main__':
    unittest.main()
