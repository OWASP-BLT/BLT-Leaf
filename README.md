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

### Core Functionality
- 📝 **Track Open PRs**: Add GitHub PR URLs to track their readiness (open PRs only)
- 📊 **Sortable Table View**: View PRs in a compact, sortable table with check results, review status, and files changed
- 👥 **Multi-Repo Support**: Track PRs across multiple repositories
- 🔄 **Real-time Updates**: Refresh PR data from GitHub API
- 🎨 **Clean Interface**: Simple, GitHub-themed UI with dark mode support
- 🔐 **GitHub OAuth Authentication**: Per-user authentication with secure token management
- 🔔 **Webhook Integration (NEW)**: Automatically track new PRs when opened via GitHub webhooks

### Authentication & Rate Limiting
- 🔑 **OAuth Login**: Login with your GitHub account for personalized rate limits
- 👤 **Per-User Tokens**: Each user's API requests use their own GitHub token
- 📈 **Independent Rate Limits**: No more shared rate limit exhaustion
- 🔒 **Secure Token Storage**: OAuth tokens encrypted at rest in database
- 🚀 **Seamless Experience**: Automatic session management with localStorage

### PR Readiness Analysis
- 🎯 **Readiness Scoring**: Data-driven 0-100 score combining CI confidence and review health
- 📈 **Timeline Tracking**: Complete chronological view of commits, reviews, and comments
- 🔍 **Feedback Loop Detection**: Automatically tracks reviewer comments and author responses
- 📊 **Response Rate Analysis**: Measures how quickly and thoroughly authors address feedback
- ⚠️ **Stale Feedback Detection**: Identifies unaddressed comments older than 3 days
- 🚫 **Smart Blocker Detection**: Auto-identifies issues preventing merge (failing checks, merge conflicts, etc.)
- 💡 **Actionable Recommendations**: Context-aware suggestions for next steps

### Performance & Protection
- ⚡ **Response Caching**: 10-minute cache for readiness results with automatic cache headers
- 🔄 **Smart Cache Invalidation**: Auto-clears cache when PRs are manually refreshed
- 🛡️ **Rate Limiting**: Application-level protection (10 req/min per IP) for analysis endpoints
- 📊 **GitHub API Optimization**: Intelligent caching minimizes API usage
- ✅ **Merge Ready Indicator**: Clear verdict on whether PR is safe to merge

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

5. Create `.env` file and populate it with Database ID from previous step:
```bash
cp .env.example .env
```

6. Initialize the database schema:
```bash
wrangler d1 execute pr_tracker --file=./schema.sql
```

7. **Set up GitHub OAuth (Required for per-user authentication):**

   a. Create a GitHub OAuth App:
   - Go to [GitHub Settings → Developer Settings → OAuth Apps](https://github.com/settings/developers)
   - Click "New OAuth App"
   - Fill in the details:
     - **Application name**: BLT-Leaf (or your preferred name)
     - **Homepage URL**: `https://your-worker.workers.dev` (or your custom domain)
     - **Authorization callback URL**: `https://your-worker.workers.dev/api/auth/github/callback`
   - Click "Register application"
   - Note your **Client ID** and generate a new **Client Secret**

   b. Configure OAuth secrets:
   ```bash
   # Set GitHub OAuth Client ID
   wrangler secret put GITHUB_OAUTH_CLIENT_ID
   # Paste your Client ID when prompted
   
   # Set GitHub OAuth Client Secret
   wrangler secret put GITHUB_OAUTH_CLIENT_SECRET
   # Paste your Client Secret when prompted
   
   # Set Session Secret (generate a random 32+ character string)
   wrangler secret put SESSION_SECRET
   # Paste a secure random string when prompted
   # You can generate one with: openssl rand -base64 32
   ```

   c. For local development, create a `.dev.vars` file:
   ```
   GITHUB_OAUTH_CLIENT_ID=your_client_id_here
   GITHUB_OAUTH_CLIENT_SECRET=your_client_secret_here
   SESSION_SECRET=your_random_secret_here
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

### Testing

The application includes comprehensive test suites for rate limiting and caching features.

**Quick Local Test** (watch wrangler console for logs):
```bash
node test-simple.js
```

**Full Production Test** (requires deployment):
```bash
npm run deploy
node test-production.js https://your-worker.workers.dev
```

For detailed testing instructions and expected behavior, see [TESTING.md](TESTING.md).

**Note**: Local development (`wrangler dev`) may not preserve worker state between requests. For accurate rate limiting and caching tests, deploy to production.

## Usage

### Authentication
1. **Login with GitHub OAuth**:
   - Click the "Login with GitHub" button in the top-right corner
   - You'll be redirected to GitHub to authorize the application
   - After authorization, you'll be redirected back and automatically logged in
   - Your session is saved in localStorage for convenience
   
2. **Benefits of Logging In**:
   - **Higher Rate Limits**: Use your personal GitHub rate limit (5,000 requests/hour) instead of the shared unauthenticated limit (60 requests/hour)
   - **Private Repository Access**: Access PRs from private repositories you have access to
   - **No PAT Required**: No need to manually provide a Personal Access Token
   
3. **Unauthenticated Usage**:
   - You can still use the app without logging in
   - Requests will use GitHub's unauthenticated rate limit (60 requests/hour)
   - Only public repositories are accessible

### Basic Tracking
1. **Add a PR**: Enter a GitHub PR URL in the format `https://github.com/owner/repo/pull/number`
   - Note: Only open PRs can be added. Merged or closed PRs will be rejected.
2. **View Details**: See PRs in a sortable table with:
   - Repository and PR number
   - Author
   - Review status
   - Mergeable state
   - Files changed count
   - Check status (passed/failed/skipped)
   - Last updated time
3. **Sort PRs**: Click any column header to sort by that column
   - Sorting works across all pages (server-side sorting)
   - Click again to toggle ascending/descending order
   - Sorting resets to page 1 for consistent results
4. **Filter by Repo**: Click on a repository in the sidebar to filter PRs
5. **Refresh Data**: Use the refresh button to update PR information from GitHub
   - Note: If a PR has been merged or closed since being added, it will be automatically removed from tracking.

### PR Readiness Analysis
6. **Check Readiness**: Click the "Check Readiness" button on any PR row to analyze:
   - **Overall Score**: 0-100 combining CI confidence (60%) and review health (40%)
   - **Score Breakdown**: See individual CI and review scores
   - **Blockers**: Critical issues preventing merge (failing checks, conflicts, stale feedback)
   - **Warnings**: Non-blocking concerns (awaiting approval, large PR size)
   - **Recommendations**: Specific actionable next steps
   - **Response Metrics**: Author responsiveness and feedback address rate

### Readiness Classifications
- ✅ **READY_TO_MERGE** (70-100): No blockers, all key metrics passing
- 🟡 **NEARLY_READY** (60-69): Minor issues, mostly ready
- 🟠 **NEEDS_WORK** (40-59): Significant issues need attention
- 🔴 **NOT_READY** (<40): Major problems, not safe to merge

### Review Health States
- **APPROVED** (90-100): Reviews approved, ready to go
- **ACTIVE** (70-85): Good progress with responsive author
- **AWAITING_REVIEWER** (60-80): Author responded, waiting on reviewers
- **AWAITING_AUTHOR** (35-55): Author needs to address feedback
- **STALLED** (10-30): Unaddressed feedback >3 days old
- **NO_ACTIVITY** (50): No reviews or feedback yet

## API Endpoints

### Authentication Endpoints (NEW)
- `GET /api/auth/github` - Initiate GitHub OAuth flow
  - Returns redirect URL to GitHub authorization page
- `GET /api/auth/github/callback` - OAuth callback handler
  - Exchanges authorization code for access token
  - Creates user session and returns session token
- `GET /api/auth/me` - Get current user information
  - Returns user profile if authenticated
- `POST /api/auth/logout` - Logout and destroy session
  - Requires `Authorization: Bearer <session_token>` header

### Core Endpoints
- `GET /` - Serves the HTML interface
- `GET /api/repos` - List all repositories with open PRs
- `GET /api/prs` - List all open PRs with pagination and sorting
  - Query parameters:
    - `?repo=owner/name` - Filter by repository (optional)
    - `?page=N` - Page number (default: 1)
    - `?sort_by=column` - Sort column (default: `last_updated_at`)
    - `?sort_dir=asc|desc` - Sort direction (default: `desc`)
  - Supported sort columns: `title`, `author_login`, `pr_number`, `files_changed`, `checks_passed`, `checks_failed`, `checks_skipped`, `review_status`, `mergeable_state`, `commits_count`, `behind_by`, `ready_score`, `ci_score`, `review_score`, `response_score`, `feedback_score`, `last_updated_at`
- `POST /api/prs` - Add a new PR (body: `{"pr_url": "..."}`)
  - Returns 400 error if PR is merged or closed
- `POST /api/refresh` - Refresh a PR's data (body: `{"pr_id": 123}`)
  - Automatically removes PR if it has been merged or closed
- `GET /api/rate-limit` - Check GitHub API rate limit status
- `GET /api/status` - Check database configuration status

### Analysis Endpoints (NEW)
- `GET /api/prs/{id}/timeline` - Get complete PR event timeline
  - Returns chronological list of commits, reviews, and comments
  - Includes parsed timestamps and event metadata
  
- `GET /api/prs/{id}/review-analysis` - Analyze review feedback loops
  - Detects reviewer feedback and author responses
  - Calculates response rates and timing
  - Identifies stale unaddressed feedback
  - Returns review health classification and score
  
- `GET /api/prs/{id}/readiness` - Get comprehensive PR readiness analysis
  - Combines CI confidence and review health scores
  - Detects blockers (failing checks, conflicts, stale feedback)
  - Provides actionable recommendations
  - Returns merge-ready verdict with detailed breakdown

### Webhook Endpoint (NEW)
- `POST /api/github/webhook` - GitHub webhook integration for automatic PR tracking
  - Automatically adds new PRs to tracking when they are opened
  - Updates existing PRs when they are modified (synchronize, edited, reviews, checks)
  - Removes PRs from tracking when they are closed or merged
  - Supported webhook events:
    - `pull_request.opened` - Automatically adds PR to tracking
    - `pull_request.closed` - Removes PR from tracking
    - `pull_request.reopened` - Re-adds PR to tracking
    - `pull_request.synchronize` - Updates PR when new commits are pushed
    - `pull_request.edited` - Updates PR when details change
    - `pull_request_review.*` - Updates PR data including behind_by and mergeable_state
    - `check_run.*` - Updates PR data including behind_by and mergeable_state
    - `check_suite.*` - Updates PR data including behind_by and mergeable_state
  - Security: Verifies GitHub webhook signatures using `GITHUB_WEBHOOK_SECRET`

#### Setting Up GitHub Webhooks
To enable automatic PR tracking:

1. Go to your repository settings → Webhooks → Add webhook
2. Set Payload URL to: `https://your-worker.workers.dev/api/github/webhook`
3. Set Content type to: `application/json`
4. Set Secret to a secure random string
5. Select events to send:
   - ✓ Pull requests
   - ✓ Pull request reviews (optional)
   - ✓ Check runs (optional)
6. Add the webhook secret to your Cloudflare Worker environment:
   ```bash
   wrangler secret put GITHUB_WEBHOOK_SECRET
   ```

Once configured, new PRs will be automatically added to tracking when opened!

### Response Examples

#### Timeline Response
```json
{
  "pr": { "id": 1, "title": "...", "author": "..." },
  "timeline": [
    {
      "type": "commit",
      "timestamp": "2024-01-15T10:30:00Z",
      "author": "username",
      "data": { "sha": "abc1234", "message": "Fix bug" }
    },
    {
      "type": "review_comment",
      "timestamp": "2024-01-15T11:00:00Z",
      "author": "reviewer",
      "data": { "body": "Please add tests", "path": "src/main.py" }
    }
  ],
  "event_count": 15
}
```

#### Readiness Response
```json
{
  "pr": { "id": 1, "title": "...", "state": "open" },
  "readiness": {
    "overall_score": 78,
    "overall_score_display": "78%",
    "ci_score": 100,
    "ci_score_display": "100%",
    "review_score": 70,
    "review_score_display": "70%",
    "classification": "READY_TO_MERGE",
    "merge_ready": true,
    "blockers": [],
    "warnings": ["Awaiting reviewer approval"],
    "recommendations": ["Ping reviewers for re-review"]
  },
  "review_health": {
    "classification": "AWAITING_REVIEWER",
    "score": 70,
    "score_display": "70%",
    "response_rate": 1.0,
    "response_rate_display": "100%",
    "total_feedback": 3,
    "responded_feedback": 3
  },
  "ci_checks": {
    "passed": 5,
    "failed": 0,
    "skipped": 0
  }
}
```

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

## Readiness Scoring Algorithm

### Overall Score Calculation
```
Overall Score = (CI Confidence × 60%) + (Review Health × 40%)
```

### CI Confidence Score (0-100)
- **All passing**: 100 points
- **Any failing**: Heavily penalized (0 points if all fail)
- **Skipped checks**: Minor penalty (−20% per skipped)
- **Pass rate**: `(passed / total) × 100 - (failed / total) × 80 - (skipped / total) × 20`

### Review Health Score (0-100)
Based on review state and responsiveness:
- **APPROVED**: 95 points (reviews approved)
- **ACTIVE**: 70-85 points (good back-and-forth, responsive author)
- **AWAITING_REVIEWER**: 60-80 points (author responded, waiting on reviewers)
- **AWAITING_AUTHOR**: 35-55 points (needs author response)
- **STALLED**: 10-30 points (unaddressed feedback >3 days)
- **NO_ACTIVITY**: 50 points (no reviews yet)

### Feedback Loop Detection
The system tracks reviewer-author interaction cycles:
1. **Reviewer Action**: Review submission or comment
2. **Author Response**: Commit, reply, or code change
3. **Response Tracking**: Measures time between feedback and response
4. **Staleness Detection**: Flags feedback >3 days without response

### Automatic Blocker Detection
- ❌ Failing CI checks
- ❌ Merge conflicts (dirty mergeable state)
- ❌ PR closed or already merged
- ❌ Stale unaddressed feedback (>3 days)
- ❌ Awaiting author response to change requests

### Smart Recommendations
Context-aware suggestions based on PR state:
- Fix specific failing checks
- Address reviewer comments
- Resolve merge conflicts
- Ping reviewers for approval
- Split large PRs (>30 files)
- Re-run flaky checks

## GitHub API & Rate Limits

The application uses the GitHub REST API to fetch PR information.

### Rate Limits
- **Unauthenticated**: 60 requests per hour (shared IP-based limit)
- **Authenticated (OAuth)**: 5,000 requests per hour per user
- **GitHub App** (future): Higher limits per installation

### Authentication Methods

1. **GitHub OAuth (Recommended)**
   - Users login with their GitHub account
   - Each user gets their own rate limit (5,000 req/hour)
   - No shared rate limit exhaustion
   - Access to private repositories
   - Automatic token management

2. **Unauthenticated (Fallback)**
   - No login required
   - Limited to public repositories
   - Shared rate limit of 60 req/hour
   - Suitable for light usage or public projects

### Token Security
- OAuth tokens are encrypted at rest using HMAC-SHA256
- Session tokens are stored in localStorage on client
- Server-side session validation on each request
- Tokens can be revoked via logout or GitHub settings

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is part of the OWASP Bug Logging Tool (BLT) project. 
