# BLT-Leaf Test Suite

This directory contains automated tests for the BLT-Leaf PR Readiness Checker application.

## Test Structure

### Backend Tests (`test_backend.py`)
Python unit tests for backend functionality:
- **parse_pr_url()**: Tests URL parsing for GitHub PR URLs
  - Valid HTTPS/HTTP URLs
  - Invalid URL formats
  - Edge cases (trailing slashes, special characters, large PR numbers)

### Configuration Tests (`test_config.py`)
Python tests for configuration validation:
- **Configuration Files**: Validates existence of required files
  - wrangler.toml, schema.sql, package.json
  - src/index.py, public/index.html
- **Schema Validation**: Validates database schema structure
  - Required fields and data types
  - Indexes and constraints

### Frontend Tests (`test_frontend.html`)
Browser-based JavaScript tests (run manually in browser):
- **escapeHtml()**: Tests HTML escaping for XSS prevention
  - Special character escaping
  - Quote and ampersand handling
- **timeAgo()**: Tests relative time display
  - Various time intervals (seconds, minutes, hours, days)
  - Singular/plural forms

## Running Tests

### Run All Tests
```bash
npm test
```

### Run Backend Tests Only
```bash
python3 -m unittest discover -s tests -p "test_*.py" -v
```

### Run Frontend Tests Manually
Open `tests/test_frontend.html` in a web browser to see interactive test results.

Or start a simple HTTP server:
```bash
python3 -m http.server 8080 --directory tests
# Then open: http://localhost:8080/test_frontend.html
```

## Continuous Integration

Tests automatically run on GitHub Actions for:
- Push to main, master, or develop branches
- Pull requests to main, master, or develop branches

The CI workflow includes:
1. **Backend Python Tests**: Unit tests for core functionality
2. **Frontend Validation**: Validates that frontend test file exists and is well-formed
3. **Configuration Validation**: Validates project configuration files and Python syntax

See `.github/workflows/test.yml` for the complete CI configuration.

## Test Coverage

Current test coverage includes:
- ✅ URL parsing logic (6 tests)
- ✅ Configuration file validation (10 tests)
- ✅ Schema structure validation (6 tests)
- ✅ HTML escaping (security) - frontend manual tests
- ✅ Time formatting - frontend manual tests

**Total: 22 automated backend tests + manual frontend tests**

## Future Test Additions

Potential areas for expanded test coverage:
- API endpoint integration tests (would require mock D1 database)
- Database query tests with SQLite
- GitHub API interaction tests (with mocking)
- End-to-end workflow tests
- Error handling tests
- Rate limiting behavior
- Automated browser-based frontend tests (currently manual)
