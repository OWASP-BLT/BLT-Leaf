# Authentication and Refresh Tracking

This document describes the GitHub authentication requirement for refreshing PRs and the comprehensive history tracking feature.

## Overview

PR refresh functionality now requires users to authenticate with their GitHub username. All PR activity is tracked in a comprehensive history system, recording:
- Who refreshed the PR
- When it was refreshed
- All state changes (merged status, review status, checks)
- Total activity count

## New Feature: Activity Timeline in Right Panel

Each PR's activity history is displayed in a dedicated right-hand column:
- **Hover interaction**: Timeline updates automatically when hovering over PR cards
- **Always visible**: Dedicated panel (320px) on large screens
- **Summary statistics**: Shows total events and refresh counts
- **Placeholder**: Displays "Hover over a PR to see its history" when no PR is active

### Timeline Action Types

The timeline displays different types of events with distinct icons:
- 🔄 **Refresh**: User-initiated PR data refresh
- ➕ **Added**: PR was added to the tracker
- 📝 **State Change**: PR state changed (open/closed/merged)
- 👁 **Review Change**: Review status changed (approved, changes requested, etc.)
- ⚙️ **Checks Change**: CI/CD check status changed

### Timeline Display

The timeline appears in a dedicated right-hand column and updates on hover:

**When hovering a PR:**
```
ACTIVITY TIMELINE
─────────────────
Total Activity
12 events
8 refreshes by 3 users
─────────────────

🔄  PR refreshed by alice
    by alice · 5 minutes ago

📝  Review status changed to approved
    by alice · 1 hour ago

⚙️  Checks: 5 passed, 0 failed, 0 skipped
    by alice · 2 hours ago

🔄  PR refreshed by bob
    by bob · 3 hours ago

➕  PR #42 added to tracker
    2 days ago
```

**When not hovering:**
```
ACTIVITY TIMELINE
─────────────────

Hover over a PR to see its history
```

## How It Works

### Frontend Authentication

1. **Login Flow**:
   - User clicks "Login" button in the header
   - A simple prompt asks for their GitHub username
   - Username is stored in browser's localStorage
   - UI updates to show logged-in state

2. **Logout Flow**:
   - User clicks "Logout" button
   - Username is removed from localStorage
   - UI updates to show logged-out state

3. **Refresh Requirement**:
   - When a user tries to refresh a PR without being logged in, they are prompted to log in
   - Authenticated users can refresh PRs, and their username is sent with the request

### Backend Authentication

1. **Simple Token-Based Auth**:
   - Frontend sends username in the `Authorization` header
   - Backend validates the presence of the Authorization header
   - For simplicity, the username is trusted (no password verification)
   
   **Note**: This is a simplified authentication mechanism suitable for tracking purposes. In production, consider implementing:
   - OAuth flow with GitHub
   - JWT tokens
   - Session management with secure cookies
   - Token verification against a session store

2. **Refresh Tracking**:
   - Each refresh creates a record in the `pr_history` table
   - Records include: PR ID, action type, actor, description, state snapshots, and timestamp
   - Refresh count is calculated on-demand from the history table

### Database Schema

The `pr_history` table:
```sql
CREATE TABLE IF NOT EXISTS pr_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pr_id INTEGER NOT NULL,
    action_type TEXT NOT NULL, -- 'refresh', 'state_change', 'review_change', 'checks_change', 'added'
    actor TEXT, -- GitHub username who performed the action
    description TEXT, -- Human-readable description of the change
    before_state TEXT, -- JSON snapshot of relevant state before change
    after_state TEXT, -- JSON snapshot of relevant state after change
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (pr_id) REFERENCES prs(id) ON DELETE CASCADE
);
```

Indexes:
- `idx_pr_history_pr_id` on `pr_id` for fast lookup by PR
- `idx_pr_history_actor` on `actor` for fast lookup by user
- `idx_pr_history_action_type` on `action_type` for filtering by type

## API Endpoints

### POST /api/refresh
Refresh a PR's data (requires authentication).

**Headers**:
```
Content-Type: application/json
Authorization: <username>
```

**Request Body**:
```json
{
  "pr_id": 123
}
```

**Response** (Success):
```json
{
  "success": true,
  "data": { /* PR data */ },
  "refresh_count": 5,
  "refreshed_by": "username",
  "changes_detected": 2
}
```

**Response** (Unauthorized):
```json
{
  "error": "Authentication required. Please log in with GitHub to refresh PRs."
}
```

### GET /api/pr-history/{pr_id}
Get full activity history for a specific PR.

**Response**:
```json
{
  "refresh_count": 5,
  "unique_users": 3,
  "history": [
    {
      "action_type": "refresh",
      "actor": "alice",
      "description": "PR refreshed by alice",
      "before_state": null,
      "after_state": null,
      "created_at": "2024-01-15T10:30:00Z"
    },
    {
      "action_type": "state_change",
      "actor": "alice",
      "description": "State changed from open to closed",
      "before_state": "{\"state\": \"open\"}",
      "after_state": "{\"state\": \"closed\"}",
      "created_at": "2024-01-15T09:00:00Z"
    },
    {
      "action_type": "added",
      "actor": null,
      "description": "PR #42 added to tracker",
      "before_state": null,
      "after_state": null,
      "created_at": "2024-01-14T15:45:00Z"
    }
  ]
}
```

## Layout Structure

3-column layout on large screens (≥1024px):
- **Left**: Repository sidebar (288px)
- **Center**: PR cards (flexible width)
- **Right**: Activity timeline panel (320px)

On smaller screens (<1024px), the timeline panel is hidden to preserve space for PR cards.

## Authentication Model

Simplified username-based system for tracking attribution:
- Client provides GitHub username (not verified against GitHub API)
- Username validated for format compliance on both client and server
- No passwords or OAuth tokens (intentional for low-stakes tracking use case)
- Suitable for analytics and audit trails; not for access control

Production deployments requiring verified identity should implement GitHub OAuth flow and JWT tokens.

## Security Considerations

### Current Implementation

The current authentication model is intentionally simple and focused on activity tracking rather than access control:

1. **Username Validation**:
   - Client-side: Format validation (1-39 chars, alphanumeric + hyphens)
   - Server-side: Same format validation
   - No verification against GitHub's API

2. **No Secrets**:
   - No passwords stored or transmitted
   - No tokens beyond the username itself
   - Username stored in browser's localStorage

3. **Use Case**:
   - Designed for tracking who performed actions
   - Not suitable for preventing unauthorized access
   - Assumes trusted users in a team environment

### Recommended Production Enhancements

For production deployments with sensitive data or untrusted users:

1. **OAuth Integration**:
   - Implement GitHub OAuth flow
   - Verify user identity against GitHub
   - Use OAuth tokens for API access

2. **Session Management**:
   - Server-side session storage
   - Secure, HttpOnly cookies
   - CSRF protection

3. **JWT Tokens**:
   - Signed tokens for authentication
   - Expiration and refresh mechanisms
   - Token validation on every request

4. **Access Control**:
   - Role-based permissions
   - Rate limiting per user
   - Audit logs for all actions

## Migration from Existing Deployments

The database schema automatically migrates existing installations:

1. **First Request**: When the first API request is made after deployment, the `init_database_schema()` function:
   - Creates the `pr_history` table if it doesn't exist
   - Adds indexes for optimal query performance
   - Existing PRs remain unchanged

2. **No Data Loss**: All existing PR data is preserved. Only the new history tracking table is added.

3. **Backward Compatibility**: The API remains compatible with existing clients, except for the authentication requirement on `/api/refresh`.

## Testing Authentication

### Manual Testing

1. **Without Authentication**:
   ```bash
   curl -X POST http://localhost:8787/api/refresh \
     -H "Content-Type: application/json" \
     -d '{"pr_id": 1}'
   ```
   Expected: 401 Unauthorized

2. **With Authentication**:
   ```bash
   curl -X POST http://localhost:8787/api/refresh \
     -H "Content-Type: application/json" \
     -H "Authorization: testuser" \
     -d '{"pr_id": 1}'
   ```
   Expected: 200 OK with refresh data

3. **View History**:
   ```bash
   curl http://localhost:8787/api/pr-history/1
   ```
   Expected: JSON with history entries

### UI Testing

1. Open the application in a browser
2. Verify login button is visible when not authenticated
3. Click login, enter a username
4. Verify logout button appears and username is displayed
5. Try refreshing a PR - should succeed
6. Logout and try refreshing - should show error message
7. Hover over a PR card to see timeline panel update
