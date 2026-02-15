# Timeline Feature Visual Guide

## How the Timeline Appears

### Collapsed State (Default)
```
┌─────────────────────────────────────────────────────────────────┐
│ PR Card                                                          │
│                                                                  │
│ Refreshed 8 times by 3 users    [▸ History] [Refresh] (5m ago) │
└─────────────────────────────────────────────────────────────────┘
```

### Expanded State (After clicking History button)
```
┌─────────────────────────────────────────────────────────────────┐
│ PR Card                                                          │
│                                                                  │
│ Refreshed 8 times by 3 users    [▾ History] [Refresh] (5m ago) │
├─────────────────────────────────────────────────────────────────┤
│ ACTIVITY TIMELINE                                                │
│ ┌───────────────────────────────────────────────────────────┐   │
│ │ 🔄  PR refreshed by alice                                  │   │
│ │     by alice · 5 minutes ago                              │   │
│ │                                                            │   │
│ │ 📝  Review status changed to approved                      │   │
│ │     1 hour ago                                             │   │
│ │                                                            │   │
│ │ ⚙️  Checks: 5 passed, 0 failed, 0 skipped                  │   │
│ │     2 hours ago                                            │   │
│ │                                                            │   │
│ │ 🔄  PR refreshed by bob                                    │   │
│ │     by bob · 3 hours ago                                   │   │
│ │                                                            │   │
│ │ 👁  Review status changed to pending                       │   │
│ │     5 hours ago                                            │   │
│ │                                                            │   │
│ │ ➕  PR #42 added to tracker                                │   │
│ │     2 days ago                                             │   │
│ └───────────────────────────────────────────────────────────┘   │
│                    (Scrollable if > 10 entries)                  │
└─────────────────────────────────────────────────────────────────┘
```

## Action Types and Icons

| Icon | Action Type      | Description                           | Has Actor? |
|------|------------------|---------------------------------------|------------|
| 🔄   | refresh          | User manually refreshed the PR        | Yes        |
| ➕   | added            | PR was added to the tracker           | No         |
| 📝   | state_change     | PR state changed (open/closed/merged) | Yes*       |
| 👁   | review_change    | Review status changed                 | Yes*       |
| ⚙️   | checks_change    | CI/CD checks status changed           | Yes*       |

*Actor is the user who triggered the refresh that detected the change.

## Key Features

1. **Compact Design**: Each entry is just 2-3 lines
2. **Color-Coded Icons**: Different colors for different action types
3. **Actor Attribution**: Shows who performed the action when applicable
4. **Relative Timestamps**: "5 minutes ago" instead of absolute dates
5. **Scrollable**: Max height with scroll for long histories
6. **On-Demand Loading**: Timeline loads only when expanded
7. **Toggle Behavior**: Click again to collapse

## Example Timeline Data

```json
[
  {
    "action_type": "refresh",
    "actor": "alice",
    "description": "PR refreshed by alice",
    "created_at": "2024-01-15T10:30:00Z"
  },
  {
    "action_type": "review_change",
    "actor": null,
    "description": "Review status changed to approved",
    "created_at": "2024-01-15T09:00:00Z"
  },
  {
    "action_type": "checks_change",
    "actor": null,
    "description": "Checks: 5 passed, 0 failed, 0 skipped",
    "created_at": "2024-01-15T08:00:00Z"
  },
  {
    "action_type": "added",
    "actor": null,
    "description": "PR #42 added to tracker",
    "created_at": "2024-01-14T15:45:00Z"
  }
]
```

## Implementation Details

### Frontend
- Uses Tailwind CSS for styling
- Timeline expands below PR card (not on the right side for better mobile support)
- Data fetched from `/api/pr-history/{pr_id}` endpoint
- Lazy loading: history only fetched when user clicks expand

### Backend
- `pr_history` table stores all actions
- Automatic change detection during refresh
- Tracks before/after state for changes
- Migration from old `refresh_history` table
