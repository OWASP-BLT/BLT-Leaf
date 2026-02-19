# OAuth Authentication - UI Changes Visualization

## Header Changes

### Before (Without OAuth)
```
┌─────────────────────────────────────────────────────────────────────┐
│  🏠 BLT-LEAF    [Search Box]    🔄 🌙 ❓ v0.0.x  GitHub            │
└─────────────────────────────────────────────────────────────────────┘
```

### After (With OAuth - Logged Out)
```
┌─────────────────────────────────────────────────────────────────────┐
│  🏠 BLT-LEAF  [Search Box]  [Login with GitHub] 🔄 🌙 ❓ v0.0.x 🐙 │
└─────────────────────────────────────────────────────────────────────┘
```

### After (With OAuth - Logged In)
```
┌─────────────────────────────────────────────────────────────────────┐
│  🏠 BLT-LEAF  [Search Box]  😀username [Logout] 🔄 🌙 ❓ v0.0.x 🐙  │
└─────────────────────────────────────────────────────────────────────┘
```

## Security Warning Banner (When ENCRYPTION_KEY not configured)

```
┌─────────────────────────────────────────────────────────────────────┐
│  ⚠️  Security Warning: ENCRYPTION_KEY not configured. GitHub        │
│      tokens are encrypted with a default key. Please configure      │
│      ENCRYPTION_KEY in your Cloudflare Worker environment.          │
└─────────────────────────────────────────────────────────────────────┘
```

## Main Layout with Timeline Panel

### Full Layout (Desktop - Width >= 1024px)
```
┌─────────────────────────────────────────────────────────────────────────┐
│                            HEADER                                        │
├──────────┬──────────────────────────────────────────┬───────────────────┤
│          │                                           │                   │
│  Repo    │           PR List                         │  Activity         │
│  Filter  │                                           │  Timeline         │
│          │  [PR Title 1] →hover→                     │  (320px)          │
│  • All   │  [PR Title 2] →hover→ ←────────loads──────│                   │
│  • org/  │  [PR Title 3] →hover→                     │  🔄 Refresh       │
│    repo1 │  [PR Title 4]                             │  username         │
│  • org/  │  [PR Title 5]                             │  2 hours ago      │
│    repo2 │                                           │                   │
│          │                                           │  ➕ Added          │
│ (288px)  │                                           │  username         │
│          │                                           │  1 day ago        │
│          │                                           │                   │
└──────────┴──────────────────────────────────────────┴───────────────────┘
```

### Mobile/Tablet Layout (Width < 1024px)
```
┌─────────────────────────────────────────┐
│            HEADER                       │
├─────────────────────────────────────────┤
│  Repo Filter (Full Width)              │
├─────────────────────────────────────────┤
│                                         │
│  PR List (Full Width)                  │
│                                         │
│  [PR Title 1]                          │
│  [PR Title 2]                          │
│  [PR Title 3]                          │
│                                         │
│  (Timeline panel hidden on mobile)     │
│                                         │
└─────────────────────────────────────────┘
```

## Timeline Panel Detail

```
┌────────────────────────────────────┐
│  Activity Timeline                 │
├────────────────────────────────────┤
│                                    │
│  Refreshed 5 times by 2 users     │
│  ────────────────────────────      │
│                                    │
│  🔄 Refresh                        │
│  username                          │
│  2024-02-19 10:30 AM              │
│  PR refreshed by username          │
│                                    │
│  📝 State Change                   │
│  username                          │
│  2024-02-19 09:15 AM              │
│  State: open → merged              │
│                                    │
│  👁️ Review Change                  │
│  username                          │
│  2024-02-18 03:20 PM              │
│  Review: pending → approved        │
│                                    │
│  ⚙️ Checks Change                  │
│  username                          │
│  2024-02-18 02:45 PM              │
│  Checks: running → passed          │
│                                    │
│  ➕ Added                          │
│  username                          │
│  2024-02-17 11:00 AM              │
│  PR added to tracker               │
│                                    │
└────────────────────────────────────┘
```

## Hover Interaction Flow

```
Step 1: User hovers over PR row
┌─────────────────────────────┐
│  [PR #123: Fix bug] ← hover │
└─────────────────────────────┘
         ↓
Step 2: JavaScript calls API
         ↓
   GET /api/pr-history/123
         ↓
Step 3: Timeline panel updates
┌──────────────────────┐
│  Activity Timeline   │
│  ──────────────────  │
│  [History for PR 123]│
│  🔄 Refresh...       │
│  📝 State change...  │
└──────────────────────┘
```

## Login Flow Visualization

```
1. User clicks "Login with GitHub"
   ↓
2. Redirect to GitHub OAuth
   ┌──────────────────────────┐
   │  Authorize BLT-Leaf?     │
   │                          │
   │  Permissions:            │
   │  • Access repositories   │
   │  • Read user profile     │
   │                          │
   │  [Authorize] [Cancel]    │
   └──────────────────────────┘
   ↓
3. GitHub redirects back with code
   /api/auth/github/callback?code=XXX
   ↓
4. Backend exchanges code for token
   ↓
5. Token encrypted and stored
   ↓
6. Frontend receives encrypted token
   ↓
7. UI updates to logged-in state
   ┌──────────────────────────┐
   │  😀 username [Logout]    │
   └──────────────────────────┘
```

## Button States

### Login Button (Not Logged In)
```
┌─────────────────────────────┐
│  🐙 Login with GitHub       │  ← Green, clickable
└─────────────────────────────┘
```

### User Display (Logged In)
```
┌──────────────┬──────────────┐
│  😀 username │  [Logout]    │  ← Avatar + name, gray logout
└──────────────┴──────────────┘
```

## Refresh Button Behavior

### Without Authentication
```
User clicks Refresh
      ↓
❌ Error: "Authentication required. Please log in with GitHub to refresh PRs."
```

### With Authentication
```
User clicks Refresh
      ↓
✅ Success: PR data refreshed
      ↓
History entry created:
{
  action_type: 'refresh',
  actor: 'username',
  description: 'PR refreshed by username',
  created_at: '2024-02-19T10:30:00Z'
}
```

## Activity Icons

The timeline uses emoji icons to represent different actions:

- 🔄 **Refresh**: User manually refreshed PR data
- ➕ **Added**: PR was added to the tracker
- 📝 **State Change**: PR state changed (open → closed, open → merged, etc.)
- 👁️ **Review Change**: Review status changed (pending → approved, etc.)
- ⚙️ **Checks Change**: CI checks status changed (running → passed, etc.)

## Color Coding

### Timeline Entry Borders
```
🔄 Refresh      → Blue border
➕ Added        → Green border  
📝 State Change → Yellow border
👁️ Review Change → Purple border
⚙️ Checks Change → Orange border
```

### Status Colors
```
✅ Success/Passed  → Green
❌ Failed/Error    → Red
⚠️  Warning        → Yellow
ℹ️  Info           → Blue
⏳ Pending         → Gray
```

## Responsive Breakpoints

```
< 640px (sm)     → Mobile: Repo filter full width, no timeline
640px - 768px    → Tablet: Repo filter sidebar, no timeline
768px - 1024px   → Small desktop: Repo filter sidebar, no timeline
>= 1024px (lg)   → Full desktop: All panels visible including timeline
```

## Key CSS Classes

### Authentication
- `#loginBtn` - Green GitHub-branded login button
- `#logoutBtn` - Gray logout button (hidden when logged out)
- `#usernameDisplay` - Shows username and avatar when logged in
- `#securityWarning` - Yellow warning banner

### Timeline
- `#timelinePanel` - Right sidebar (320px, hidden on < 1024px)
- `#timelineContent` - Container for activity entries
- `.timeline-entry` - Individual activity item
- `.timeline-icon` - Emoji icon for action type

## Implementation Details

### HTML Structure
```html
<header>
  <div class="auth-container">
    <button id="loginBtn">Login with GitHub</button>
    <span id="usernameDisplay" class="hidden">username</span>
    <button id="logoutBtn" class="hidden">Logout</button>
  </div>
</header>

<div id="securityWarning" class="hidden">
  ⚠️ Security Warning...
</div>

<div class="main-layout">
  <aside class="repo-filter">...</aside>
  <main class="pr-list">...</main>
  <aside id="timelinePanel" class="hidden lg:block lg:w-80">
    <h2>Activity Timeline</h2>
    <div id="timelineContent">...</div>
  </aside>
</div>
```

### JavaScript Functions
```javascript
// Authentication
login()                    // Redirect to GitHub OAuth
handleOAuthCallback()      // Process OAuth return
logout()                   // Clear auth data
updateAuthUI()            // Update login/logout display

// Timeline
loadTimeline(prId)        // Load PR history
formatTimelineEntry()     // Format history item
clearTimeline()           // Clear timeline panel

// Storage
getUsername()             // Get from localStorage
getEncryptedToken()       // Get from localStorage
setUserData()             // Store in localStorage
clearUserData()           // Clear localStorage
```

---

**Note**: All measurements are approximate and may vary based on browser/screen size.
The actual implementation uses Tailwind CSS classes for styling.
