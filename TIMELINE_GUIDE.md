# Timeline Panel Guide

This guide explains the Activity Timeline feature in BLT-Leaf, which provides real-time visibility into all PR activity.

## Overview

The Activity Timeline is a dedicated right-hand panel that displays a comprehensive history of all actions performed on each PR. It automatically updates when you hover over PR cards, providing instant context without clicking.

## Layout

### Desktop View (≥1024px width)

The application uses a 3-column layout on large screens:

```
┌─────────────┬──────────────────────────┬────────────────┐
│             │                          │                │
│  Repos      │    PR Cards              │   Timeline     │
│  Sidebar    │    (Main Area)           │   Panel        │
│             │                          │                │
│  288px      │    Flexible              │   320px        │
│             │                          │                │
└─────────────┴──────────────────────────┴────────────────┘
```

### Mobile/Tablet View (<1024px width)

The timeline panel is hidden to maximize space for PR cards:

```
┌─────────────────────────────────────┐
│                                     │
│         Repos & PR Cards            │
│         (Stacked Layout)            │
│                                     │
│                                     │
└─────────────────────────────────────┘
```

## Interaction Model

### Hover-Based Updates

The timeline uses a **hover interaction pattern** for seamless exploration:

1. **Default State**: Shows placeholder text "Hover over a PR to see its history"
2. **On Hover**: Automatically loads and displays the PR's activity timeline
3. **On Move**: Switches to the new PR's timeline without clicking
4. **No Click Required**: Timeline updates instantly as you move your cursor

### Benefits

- **Fast Exploration**: Review multiple PR histories quickly
- **Non-Intrusive**: No page navigation or modal dialogs
- **Context Preservation**: Main view stays intact while exploring
- **Keyboard Friendly**: Works with tab navigation

## Timeline Content

### Summary Section

At the top of the timeline, you'll see aggregate statistics:

```
┌─────────────────────────────┐
│ ACTIVITY TIMELINE           │
├─────────────────────────────┤
│ Total Activity              │
│ 12 events                   │
│ 8 refreshes by 3 users      │
└─────────────────────────────┘
```

### Activity Entries

Each activity is displayed with:
- **Icon**: Visual indicator of action type (emoji)
- **Description**: Human-readable summary
- **Actor**: Username who performed the action (if applicable)
- **Timestamp**: Relative time (e.g., "5 minutes ago")
- **Color Border**: Left border color-coded by action type

Example entry:
```
🔄  PR refreshed by alice
    by alice · 5 minutes ago
    ├── Blue border
```

## Action Types

### 🔄 Refresh (Blue)

User-initiated refresh of PR data from GitHub API.

**Example**:
```
🔄  PR refreshed by alice
    by alice · 5 minutes ago
```

**When Created**: Every time someone clicks the "Update" button on a PR card.

### ➕ Added (Green)

PR was added to the tracking system.

**Example**:
```
➕  PR #123 added to tracker
    2 days ago
```

**When Created**: When a PR is first added via URL or bulk import.

### 📝 State Change (Purple)

PR's state changed (open, closed, merged).

**Example**:
```
📝  State changed from open to closed
    by alice · 1 hour ago
```

**When Created**: Automatically detected during refresh when PR state changes.

### 👁 Review Change (Yellow)

Review status changed (pending, approved, changes requested, etc.).

**Example**:
```
👁  Review status changed to approved
    by alice · 2 hours ago
```

**When Created**: Automatically detected during refresh when review status changes.

### ⚙️ Checks Change (Orange)

CI/CD check status changed.

**Example**:
```
⚙️  Checks: 5 passed, 0 failed, 0 skipped
    by alice · 3 hours ago
```

**When Created**: Automatically detected during refresh when check results change.

## Implementation Details

### Frontend

**JavaScript Functions**:
- `loadTimeline(prId)`: Fetches and displays timeline for a PR
- `clearTimeline()`: Resets timeline to default state
- `getActionIcon(actionType)`: Returns emoji for action type
- `getActionColor(actionType)`: Returns Tailwind classes for border color

**Event Handling**:
```javascript
// Added to each PR row
row.addEventListener('mouseenter', () => {
    loadTimeline(pr.id);
});
```

**API Call**:
```javascript
const response = await fetch(`/api/pr-history/${prId}`);
const data = await response.json();
```

### Backend

**Endpoint**: `GET /api/pr-history/{pr_id}`

**SQL Query**:
```sql
-- Get all history entries
SELECT action_type, actor, description, before_state, after_state, created_at
FROM pr_history
WHERE pr_id = ?
ORDER BY created_at DESC

-- Get refresh statistics
SELECT 
    COUNT(*) as refresh_count,
    COUNT(DISTINCT actor) as unique_users
FROM pr_history
WHERE pr_id = ? AND action_type = 'refresh'
```

**Response Structure**:
```json
{
  "refresh_count": 8,
  "unique_users": 3,
  "history": [
    {
      "action_type": "refresh",
      "actor": "alice",
      "description": "PR refreshed by alice",
      "before_state": null,
      "after_state": null,
      "created_at": "2024-01-15T10:30:00Z"
    }
  ]
}
```

## Visual Examples

### Example 1: Recently Added PR

```
┌─────────────────────────────────┐
│ ACTIVITY TIMELINE               │
├─────────────────────────────────┤
│ Total Activity                  │
│ 1 event                         │
│ 0 refreshes by 0 users          │
├─────────────────────────────────┤
│                                 │
│ ➕  PR #456 added to tracker   │
│     10 minutes ago              │
│                                 │
└─────────────────────────────────┘
```

### Example 2: Active PR with Multiple Updates

```
┌─────────────────────────────────┐
│ ACTIVITY TIMELINE               │
├─────────────────────────────────┤
│ Total Activity                  │
│ 15 events                       │
│ 10 refreshes by 4 users         │
├─────────────────────────────────┤
│                                 │
│ 🔄  PR refreshed by charlie     │
│     by charlie · 2 minutes ago  │
│                                 │
│ 👁  Review status changed       │
│     to approved                 │
│     by bob · 1 hour ago         │
│                                 │
│ ⚙️  Checks: 8 passed, 0 failed  │
│     by bob · 1 hour ago         │
│                                 │
│ 🔄  PR refreshed by bob         │
│     by bob · 1 hour ago         │
│                                 │
│ 📝  State changed from draft    │
│     to open                     │
│     by alice · 5 hours ago      │
│                                 │
│ ... (10 more entries)           │
│                                 │
└─────────────────────────────────┘
```

### Example 3: No Activity Yet

```
┌─────────────────────────────────┐
│ ACTIVITY TIMELINE               │
├─────────────────────────────────┤
│                                 │
│                                 │
│    Hover over a PR to see       │
│        its history              │
│                                 │
│                                 │
└─────────────────────────────────┘
```

## Styling

### Tailwind CSS Classes

**Panel Container**:
```html
<aside class="hidden lg:block lg:w-80 border-l border-slate-200 
              bg-white dark:border-slate-700 dark:bg-slate-800 
              overflow-y-auto">
```

**Summary Box**:
```html
<div class="bg-slate-50 dark:bg-slate-900 rounded-lg p-3 mb-4 
            border border-slate-200 dark:border-slate-700">
```

**Timeline Entry**:
```html
<div class="border-l-2 border-blue-400 dark:border-blue-600 pl-3 pb-3">
```

### Color Scheme

| Action Type    | Light Mode     | Dark Mode      |
|----------------|----------------|----------------|
| Refresh        | Blue (400)     | Blue (600)     |
| Added          | Green (400)    | Green (600)    |
| State Change   | Purple (400)   | Purple (600)   |
| Review Change  | Yellow (400)   | Yellow (600)   |
| Checks Change  | Orange (400)   | Orange (600)   |

## Performance Considerations

### Caching

Timeline data is fetched fresh on each hover to ensure accuracy. Consider implementing:

1. **Client-Side Cache**: Store timeline data in memory for 30 seconds
2. **Debouncing**: Add 100ms delay before loading timeline on hover
3. **Request Cancellation**: Cancel pending requests when moving to next PR

Example with debouncing:
```javascript
let hoverTimeout;
row.addEventListener('mouseenter', () => {
    clearTimeout(hoverTimeout);
    hoverTimeout = setTimeout(() => {
        loadTimeline(pr.id);
    }, 100);
});
```

### Database Indexes

Ensure these indexes exist for fast timeline queries:
- `idx_pr_history_pr_id` on `pr_id`
- `idx_pr_history_action_type` on `action_type`

## Accessibility

### Screen Readers

The timeline panel includes:
- Semantic HTML structure
- ARIA labels for action types
- Descriptive text for all entries

### Keyboard Navigation

While the hover interaction works well for mouse users, consider adding:
- Focus events alongside hover events
- Keyboard shortcuts (e.g., 't' to toggle timeline)
- Tab navigation support

Example enhancement:
```javascript
row.addEventListener('focus', () => {
    loadTimeline(pr.id);
});
```

## Customization

### Changing Panel Width

Adjust the width in two places:

1. **HTML**: Update the panel width class
```html
<aside class="lg:w-80"> <!-- Change to lg:w-96 for wider panel -->
```

2. **Responsive Breakpoint**: Adjust when panel appears
```html
<aside class="hidden xl:block"> <!-- Show only on extra-large screens -->
```

### Adding New Action Types

1. Add new action type constant
2. Update `getActionIcon()` function
3. Update `getActionColor()` function
4. Add backend logic to record new action type

Example:
```javascript
function getActionIcon(actionType) {
    const icons = {
        'refresh': '🔄',
        'added': '➕',
        'state_change': '📝',
        'review_change': '👁',
        'checks_change': '⚙️',
        'comment_added': '💬'  // New action type
    };
    return icons[actionType] || '📌';
}
```

## Troubleshooting

### Timeline Not Updating

**Check**:
1. Browser console for JavaScript errors
2. Network tab for API call success
3. Backend logs for errors in `handle_get_pr_history()`

### Timeline Shows "Failed to load"

**Possible Causes**:
- PR ID doesn't exist in database
- Database connection issue
- CORS header missing

**Solution**: Check browser console and backend logs

### Timeline Empty Despite Activity

**Possible Causes**:
- History not being recorded during refresh
- Database migration didn't run
- SQL query filtering out entries

**Solution**: Verify `pr_history` table exists and contains records

## Best Practices

1. **Keep History Concise**: Long descriptions clutter the timeline
2. **Use Clear Actor Names**: Makes it easy to identify who did what
3. **Record Significant Changes Only**: Don't spam with minor updates
4. **Include Context in Descriptions**: "Review status changed to approved" not just "Changed"
5. **Order by Recency**: Most recent events at the top
