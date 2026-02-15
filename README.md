# BLT-Leaf - PR Readiness Checker

A simple one-page application to track and monitor GitHub Pull Request readiness status.

## Quick Deploy

Deploy this application to Cloudflare Workers with one click:

[![Deploy to Cloudflare Workers](https://deploy.workers.cloudflare.com/button)](https://deploy.workers.cloudflare.com/?url=https://github.com/OWASP-BLT/BLT-Leaf)

The deploy button will automatically:
- Create a new Cloudflare Workers project
- Provision a D1 database
- Initialize the database schema
- Deploy the application

No manual configuration required!

## Project Structure

```
BLT-Leaf/
├── public/              # Static assets served by Cloudflare Workers
│   └── index.html      # Main frontend application
├── src/                # Backend Python code
│   └── index.py        # Cloudflare Worker main handler
├── schema.sql          # Database schema for D1
├── wrangler.toml       # Cloudflare Workers configuration
├── package.json        # npm scripts for deployment
├── DEPLOYMENT.md       # Detailed deployment instructions
└── README.md          # This file
```

## Features

- 📝 **Track PRs**: Add GitHub PR URLs to track their status
- 📊 **Detailed Metrics**: View merge status, files changed, check results, and review status
- 👥 **Multi-Repo Support**: Track PRs across multiple repositories
- 🔄 **Real-time Updates**: Refresh PR data from GitHub API
- 🎨 **Clean Interface**: Simple, GitHub-themed UI with no external frameworks

## Tech Stack

- **Frontend**: Single HTML page with vanilla JavaScript (no frameworks)
- **Backend**: Python on Cloudflare Workers
- **Database**: Cloudflare D1 (SQLite)
- **Styling**: Embedded CSS with GitHub-inspired theme

## Setup

### Prerequisites

- [Wrangler CLI](https://developers.cloudflare.com/workers/wrangler/install-and-update/)
- Cloudflare account

### Installation

1. Clone the repository:
```bash
git clone https://github.com/OWASP-BLT/BLT-Leaf.git
cd BLT-Leaf
```

2. Install Wrangler (if not already installed):
```bash
npm install -g wrangler
```

3. Login to Cloudflare:
```bash
wrangler login
```

4. Create the D1 database:
```bash
wrangler d1 create pr_tracker
```

5. Update `wrangler.toml` with your database ID from the previous step.

6. Initialize the database schema:
```bash
wrangler d1 execute pr_tracker --file=./schema.sql
```

### Development

Run the development server:
```bash
wrangler dev
```

The application will be available at `http://localhost:8787`

### Deployment

Deploy to Cloudflare Workers:
```bash
wrangler deploy
```

## Usage

1. **Add a PR**: Enter a GitHub PR URL in the format `https://github.com/owner/repo/pull/number`
   - Note: Only open PRs can be added. Merged or closed PRs will be rejected.
2. **View Details**: See comprehensive PR information including:
   - Merge readiness
   - Files changed count
   - Check status (passed/failed/skipped)
   - Review approval status
   - Time since last update
   - Author information
3. **Filter by Repo**: Click on a repository in the sidebar to filter PRs
4. **Refresh Data**: Use the refresh button to update PR information from GitHub
   - Note: If a PR has been merged or closed since being added, it will be automatically removed from tracking.

## API Endpoints

- `GET /` - Serves the HTML interface
- `GET /api/repos` - List all repositories with open PRs
- `GET /api/prs` - List all open PRs (optional `?repo=owner/name` filter)
- `POST /api/prs` - Add a new PR (body: `{"pr_url": "..."}`)
  - Returns 400 error if PR is merged or closed
- `POST /api/refresh` - Refresh a PR's data (body: `{"pr_id": 123}`)
  - Automatically removes PR if it has been merged or closed

## Database Schema

The application uses a single table:

```sql
CREATE TABLE prs (
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
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

## GitHub API

The application uses the GitHub REST API to fetch PR information. No authentication is required for public repositories, but rate limits apply (60 requests per hour for unauthenticated requests).

For private repositories or higher rate limits, you can add a GitHub token to the worker environment variables.

## Testing

This project includes comprehensive automated tests that run on every push and pull request.

### Running Tests Locally

```bash
# Run all tests
npm test

# Or run Python tests directly
python3 -m unittest discover -s tests -p "test_*.py" -v
```

### Test Coverage

- **Backend Python Tests** (22 tests)
  - URL parsing and validation
  - Configuration file validation
  - Database schema validation
- **Frontend JavaScript Tests** (manual)
  - HTML escaping (security)
  - Time formatting utilities
  - Open `tests/test_frontend.html` in a browser to run

### Continuous Integration

Tests automatically run via GitHub Actions on:
- Push to main, master, or develop branches
- Pull requests to these branches

See the [tests README](tests/README.md) for more details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

When contributing:
1. Ensure all tests pass: `npm test`
2. Add tests for new functionality
3. Follow the existing code style

## License

This project is part of the OWASP Bug Logging Tool (BLT) project. 
