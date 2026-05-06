-- Migration: Create flakiness detection tables
-- Created: 2026-03-11
-- Description: Add tables for CI run history, flakiness scores, and known infrastructure issue patterns

-- Per-run record for every CI job execution
CREATE TABLE IF NOT EXISTS ci_run_history (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    check_name          TEXT    NOT NULL,           -- name of the CI check / job step
    job_name            TEXT    NOT NULL,           -- GitHub Actions job name
    workflow_name       TEXT    NOT NULL,           -- workflow display name (e.g. "CI")
    workflow_run_id     INTEGER NOT NULL,           -- github.run_id
    run_attempt         INTEGER NOT NULL DEFAULT 1, -- 1 = first run, 2+ = retry
    status              TEXT    NOT NULL,           -- 'pass' | 'fail' | 'skip'
    conclusion_category TEXT    NOT NULL,           -- 'test_failure' | 'infrastructure' | 'flake_confirmed' | 'pass' | 'skip'
    commit_sha          TEXT    NOT NULL,
    pr_number           INTEGER,                    -- NULL when not a PR-triggered run
    repo                TEXT    NOT NULL,           -- "owner/repo" format
    timestamp           TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ci_run_history_lookup
    ON ci_run_history(check_name, job_name, repo, timestamp);

-- Computed flakiness scores per (repo, workflow_name, check_name, job_name) tuple
CREATE TABLE IF NOT EXISTS flakiness_scores (
    repo                 TEXT    NOT NULL,                   -- "owner/repo" format
    workflow_name        TEXT    NOT NULL,
    check_name           TEXT    NOT NULL,
    job_name             TEXT    NOT NULL,
    flakiness_score      REAL    NOT NULL DEFAULT 0.0,       -- 0.0 – 1.0
    severity             TEXT    NOT NULL DEFAULT 'stable',  -- 'stable' | 'low' | 'medium' | 'high' | 'deterministic'
    classification       TEXT    NOT NULL DEFAULT 'stable',  -- 'stable' | 'flaky' | 'deterministic'
    total_runs           INTEGER NOT NULL DEFAULT 0,
    failure_count        INTEGER NOT NULL DEFAULT 0,
    flaky_failures       INTEGER NOT NULL DEFAULT 0,         -- failures that passed on re-run
    consecutive_failures INTEGER NOT NULL DEFAULT 0,         -- current streak of consecutive failures
    last_updated         TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (repo, workflow_name, check_name, job_name)
);

CREATE INDEX IF NOT EXISTS idx_flakiness_scores_repo
    ON flakiness_scores(repo);
CREATE INDEX IF NOT EXISTS idx_flakiness_scores_lookup
    ON flakiness_scores(repo, workflow_name, check_name, job_name);

-- Seed patterns used to classify infrastructure failures separately from test flakiness
CREATE TABLE IF NOT EXISTS known_infrastructure_issues (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern     TEXT NOT NULL UNIQUE,
    category    TEXT NOT NULL DEFAULT 'infrastructure',
    description TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
INSERT OR IGNORE INTO known_infrastructure_issues (pattern, category, description) VALUES
    ('ECONNRESET',              'infrastructure', 'TCP connection reset — transient network issue'),
    ('timed_out',               'infrastructure', 'GitHub Actions step conclusion: timed_out'),
    ('timeout',                 'infrastructure', 'Generic timeout — network or infrastructure issue'),
    ('rate limit',              'infrastructure', 'API or package registry rate limit hit'),
    ('ETIMEDOUT',               'infrastructure', 'TCP connection timed out'),
    ('fetch failed',            'infrastructure', 'Network fetch failure — transient'),
    ('network error',           'infrastructure', 'Generic network error'),
    ('Could not resolve host',  'infrastructure', 'DNS resolution failure'),
    ('dependency',              'infrastructure', 'Dependency installation or resolution failure'),
    ('upstream',                'infrastructure', 'Upstream service or dependency issue');