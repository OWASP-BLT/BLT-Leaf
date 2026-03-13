-- Migration: Extend flakiness_scores keys with repo and workflow_name
-- Created: 2026-03-13
-- Description: Add repo and workflow_name to flakiness_scores for scoped lookups

CREATE TABLE IF NOT EXISTS flakiness_scores_v2 (
    repo                 TEXT    NOT NULL,
    workflow_name        TEXT    NOT NULL,
    check_name           TEXT    NOT NULL,
    job_name             TEXT    NOT NULL,
    flakiness_score      REAL    NOT NULL DEFAULT 0.0,
    severity             TEXT    NOT NULL DEFAULT 'stable',
    classification       TEXT    NOT NULL DEFAULT 'stable',
    total_runs           INTEGER NOT NULL DEFAULT 0,
    failure_count        INTEGER NOT NULL DEFAULT 0,
    flaky_failures       INTEGER NOT NULL DEFAULT 0,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_updated         TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (repo, workflow_name, check_name, job_name)
);

INSERT INTO flakiness_scores_v2 (
    repo, workflow_name, check_name, job_name, flakiness_score, severity,
    classification, total_runs, failure_count, flaky_failures,
    consecutive_failures, last_updated
)
SELECT h.repo, s.workflow_name, s.check_name, s.job_name, s.flakiness_score,
       s.severity, s.classification, s.total_runs, s.failure_count,
       s.flaky_failures, s.consecutive_failures, s.last_updated
FROM flakiness_scores s
JOIN (
    SELECT DISTINCT repo, check_name, job_name, workflow_name
    FROM ci_run_history
) h
  ON h.check_name = s.check_name
 AND h.job_name = s.job_name
 AND h.workflow_name = s.workflow_name;

DROP TABLE flakiness_scores;
ALTER TABLE flakiness_scores_v2 RENAME TO flakiness_scores;

CREATE INDEX IF NOT EXISTS idx_flakiness_scores_repo
    ON flakiness_scores(repo);
CREATE INDEX IF NOT EXISTS idx_flakiness_scores_lookup
    ON flakiness_scores(repo, workflow_name, check_name, job_name);
