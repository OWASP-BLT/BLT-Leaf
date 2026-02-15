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
   - User clicks "Login with GitHub" button in the header
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
   - Frontend sends username in the `Authorization` header as `Bearer {username}`
   - Backend validates the presence of the Authorization header
   - For simplicity, the username is trusted (no password verification)
   
   **Note**: This is a simplified authentication mechanism suitable for tracking purposes. In production, consider implementing:
   - OAuth flow with GitHub
   - JWT tokens
   - Session management with secure cookies
   - Token verification against a session store

2. **Refresh Tracking**:
   - Each refresh creates a record in the `refresh_history` table
   - Records include: PR ID, username, and timestamp
   - Refresh count is calculated on-demand from the history table

### Database Schema

The `refresh_history` table:
```sql
CREATE TABLE IF NOT EXISTS refresh_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pr_id INTEGER NOT NULL,
    refreshed_by TEXT NOT NULL,
    refreshed_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (pr_id) REFERENCES prs(id) ON DELETE CASCADE
);
```

Indexes:
- `idx_refresh_pr_id` on `pr_id` for fast lookup by PR
- `idx_refresh_user` on `refreshed_by` for fast lookup by user

## API Endpoints

### POST /api/refresh
Refresh a PR's data (requires authentication).

**Headers**:
```
Content-Type: application/json
Authorization: Bearer {github_username}
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
Get full activity history for a specific PR (replaces `/api/refresh-history`).

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
      "actor": null,
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

### GET /api/refresh-history/{pr_id} (Legacy)
Still supported for backward compatibility. Redirects to `/api/pr-history/{pr_id}`.

## UI Features

1. **Login Button**: Appears in the header when not authenticated
2. **User Info**: Shows logged-in username with logout option when authenticated
3. **Refresh Count**: Each PR card displays:
   - "Never refreshed" if refresh_count is 0
   - "Refreshed X time(s) by Y users" otherwise
4. **Right-Hand Timeline Panel**: Dedicated column showing PR activity history
   - Visible on large screens (≥1024px)
   - Updates automatically on hover over PR cards
   - Shows placeholder "Hover over a PR to see its history" when no PR is hovered
   - Displays summary statistics (total events, refresh counts)
   - Shows icons for different action types
   - Displays actors and relative timestamps
   - Fully scrollable for long histories
5. **Success Notification**: Shows refresh count and changes detected after successful refresh

## Security Considerations

### Current Implementation
- Simple username-based authentication
- Username stored in localStorage
- No password or token verification
- Trust-based system

### Recommended Production Enhancements
1. **GitHub OAuth**: Implement full OAuth flow
2. **Token Management**: Use JWT tokens with expiration
3. **Rate Limiting**: Prevent abuse of refresh endpoint
4. **Input Validation**: Validate and sanitize usernames
5. **Session Management**: Server-side session storage
6. **HTTPS Only**: Ensure all requests use HTTPS
7. **CORS Configuration**: Restrict allowed origins

## Testing

### Manual Testing Steps
1. Open the application
2. Verify "Login with GitHub" button is visible
3. Click login and enter a GitHub username
4. Verify user info appears with username
5. Try to refresh a PR
6. Verify success message shows refresh count
7. Check PR card shows refresh count
8. Click logout and verify auth state resets
9. Try to refresh without login - should prompt for login

### Expected Behavior
- Unauthenticated users cannot refresh PRs
- Authenticated users can refresh and see history
- Refresh count increments with each refresh
- Multiple users refreshing shows unique user count
