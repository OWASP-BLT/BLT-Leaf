# Timeline Feature Visual Guide

## How the Timeline Appears

### Layout Structure (3-Column Design)
```
┌────────────────┬──────────────────────────────────┬────────────────┐
│                │                                   │                │
│  Repositories  │         PR Cards                  │    Activity    │
│   (Sidebar)    │        (Main Area)                │    Timeline    │
│                │                                   │   (Right Panel)│
│   288px        │      Flexible Width               │     320px      │
│                │                                   │                │
└────────────────┴──────────────────────────────────┴────────────────┘
```

### Right Panel - Default State
```
┌────────────────────────────────────┐
│  ACTIVITY TIMELINE                 │
├────────────────────────────────────┤
│                                    │
│    Hover over a PR to see its      │
│           history                  │
│                                    │
└────────────────────────────────────┘
```

### Right Panel - When Hovering a PR
```
┌────────────────────────────────────┐
│  ACTIVITY TIMELINE                 │
├────────────────────────────────────┤
│  Total Activity                    │
│  12 events                         │
│  8 refreshes by 3 users            │
├────────────────────────────────────┤
│                                    │
│  🔄  PR refreshed by alice         │
│      by alice · 5 minutes ago      │
│                                    │
│  📝  Review status changed         │
│      by alice · 1 hour ago         │
│                                    │
│  ⚙️  Checks: 5 passed              │
│      by alice · 2 hours ago        │
│                                    │
│  🔄  PR refreshed by bob           │
│      by bob · 3 hours ago          │
│                                    │
│  (scrollable for more events)      │
│                                    │
└────────────────────────────────────┘
```

### PR Card Hover Behavior
```
Normal State:
┌─────────────────────────────────────┐
│ PR Card                             │
│ Border: gray                        │
└─────────────────────────────────────┘

Hovered State:
┌─────────────────────────────────────┐
│ PR Card                             │  → Timeline updates in right panel
│ Border: highlighted                 │
└─────────────────────────────────────┘
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

1. **Dedicated Right Panel**: Timeline always visible in fixed position (on large screens)
2. **Hover Interaction**: Timeline updates automatically when hovering over PR cards
3. **No Click Required**: More intuitive than expand/collapse buttons
4. **Summary Statistics**: Shows total events and refresh counts at top
5. **Scrollable**: Full timeline without height limitations
6. **Responsive**: Panel hidden on mobile/tablet (< 1024px), shown on desktop
7. **Placeholder Text**: Clear instruction when no PR is hovered

## Responsive Behavior

- **Desktop (≥1024px)**: 3-column layout with timeline panel
- **Tablet/Mobile (<1024px)**: 2-column or stacked layout, timeline panel hidden
- **Breakpoint**: Uses Tailwind's `lg` breakpoint for responsiveness

## User Experience Flow

1. User loads the page → sees placeholder "Hover over a PR to see its history"
2. User hovers over a PR card → timeline immediately loads and displays
3. User hovers over different PR → timeline updates to show that PR's history
4. User moves mouse away → timeline remains showing last hovered PR's history

## Implementation Details

### Frontend
- Layout: Flexbox with 3 columns
- Right panel: Fixed 320px width on large screens
- Hover detection: `mouseenter` event on PR cards
- Data fetching: `/api/pr-history/{pr_id}` endpoint
- Rendering: `loadHistoryInPanel()` and `renderTimelineInPanel()` functions

### Backend
- `pr_history` table stores all actions
- Automatic change detection during refresh
- Tracks before/after state for changes
- Migration from old `refresh_history` table

## Advantages Over Previous Design

**Before (Expandable inline timeline):**
- Required clicking "History" button
- Timeline appeared below PR card, pushing other content down
- Each PR had its own timeline section
- More vertical scrolling required

**After (Right panel with hover):**
- No clicking required, instant on hover
- Timeline in dedicated space, doesn't affect layout
- Single timeline panel for all PRs
- Cleaner PR card design without extra buttons
- Better use of horizontal screen space

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
