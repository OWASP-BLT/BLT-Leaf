-- Migration: Add canonical_url metadata and composite uniqueness for PR identity
-- Created: 2026-03-25
-- Description:
--   1) Adds canonical_url column for normalized PR URL storage
--   2) Backfills canonical_url for existing rows
--   3) Removes duplicate rows by (repo_owner, repo_name, pr_number), keeping latest id
--   4) Enforces uniqueness on (repo_owner, repo_name, pr_number)

ALTER TABLE prs ADD COLUMN canonical_url TEXT;

UPDATE prs
SET canonical_url = 'https://github.com/' || repo_owner || '/' || repo_name || '/pull/' || pr_number
WHERE canonical_url IS NULL OR canonical_url = '';

DELETE FROM prs
WHERE id NOT IN (
    SELECT MAX(id)
    FROM prs
    GROUP BY repo_owner, repo_name, pr_number
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_prs_identity_unique
ON prs(repo_owner, repo_name, pr_number);
