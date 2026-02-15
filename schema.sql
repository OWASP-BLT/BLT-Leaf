-- Database schema for PR tracker
-- Note: For existing databases, the application automatically migrates 
-- by checking for missing columns and adding them with ALTER TABLE.
-- This ensures backward compatibility when upgrading to newer versions.
CREATE TABLE IF NOT EXISTS prs (
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
    last_refreshed_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_repo ON prs(repo_owner, repo_name);
CREATE INDEX IF NOT EXISTS idx_pr_number ON prs(pr_number);

-- Table to track PR history (refreshes and state changes)
CREATE TABLE IF NOT EXISTS pr_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pr_id INTEGER NOT NULL,
    action_type TEXT NOT NULL, -- 'refresh', 'state_change', 'review_change', 'checks_change', 'added'
    actor TEXT, -- GitHub username who performed the action (can be NULL for automated changes)
    description TEXT, -- Human-readable description of the change
    before_state TEXT, -- JSON snapshot of relevant state before change
    after_state TEXT, -- JSON snapshot of relevant state after change
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (pr_id) REFERENCES prs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_history_pr_id ON pr_history(pr_id);
CREATE INDEX IF NOT EXISTS idx_history_actor ON pr_history(actor);
CREATE INDEX IF NOT EXISTS idx_history_action_type ON pr_history(action_type);
CREATE INDEX IF NOT EXISTS idx_history_created_at ON pr_history(created_at);

-- Migration for existing databases (if needed manually)
-- Run this if the automatic migration in init_database_schema fails:
-- ALTER TABLE prs ADD COLUMN last_refreshed_at TEXT;
