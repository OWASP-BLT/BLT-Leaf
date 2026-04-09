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

WITH ranked_prs AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY LOWER(repo_owner), LOWER(repo_name), pr_number
            ORDER BY readiness_computed_at DESC NULLS LAST,
                     updated_at DESC NULLS LAST,
                     id DESC
        ) AS row_num
    FROM prs
)
DELETE FROM prs
WHERE id IN (
    SELECT id
    FROM ranked_prs
    WHERE row_num > 1
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_prs_identity_unique
ON prs(repo_owner COLLATE NOCASE, repo_name COLLATE NOCASE, pr_number);
