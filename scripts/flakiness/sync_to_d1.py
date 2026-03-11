#!/usr/bin/env python3
"""
Sync local flakiness data to Cloudflare D1 via the Cloudflare REST API.

Syncs:
  1. All rows in flakiness_scores (full upsert — scores are small).
  2. ci_run_history rows for the current workflow run only (--workflow-run-id).

Credentials are read from CLI args or environment variables:
  CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_D1_DATABASE_ID, CLOUDFLARE_API_TOKEN

Usage:
  python sync_to_d1.py \\
      --workflow-run-id 12345678 \\
      [--account-id ...]  [or env CLOUDFLARE_ACCOUNT_ID]  \\
      [--database-id ...] [or env CLOUDFLARE_D1_DATABASE_ID] \\
      [--token ...]       [or env CLOUDFLARE_API_TOKEN] \\
      [--db-path ...]
"""

import argparse
import json
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(__file__))
from db_utils import get_db_connection

CF_API      = 'https://api.cloudflare.com/client/v4'
BATCH_SIZE  = 50   # rows per HTTP request to stay well under D1 payload limits


def _d1_query(account_id, db_id, token, sql, params=None):
    """Execute a single parameterised SQL statement on D1."""
    url  = f'{CF_API}/accounts/{account_id}/d1/database/{db_id}/query'
    body = {'sql': sql}
    if params is not None:
        body['params'] = params

    resp = requests.post(
        url,
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type':  'application/json',
        },
        json=body,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get('success'):
        raise RuntimeError(f'D1 query failed: {data.get("errors")}')
    return data.get('result', [])


def sync_flakiness_scores(conn, account_id, db_id, token):
    rows = conn.execute('SELECT * FROM flakiness_scores').fetchall()
    if not rows:
        print('[sync] flakiness_scores: nothing to sync.', file=sys.stderr)
        return

    sql = """
        INSERT INTO flakiness_scores
            (check_name, job_name, workflow_name, flakiness_score, severity,
             classification, total_runs, failure_count, flaky_failures,
             consecutive_failures, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(check_name, job_name) DO UPDATE SET
            workflow_name        = excluded.workflow_name,
            flakiness_score      = excluded.flakiness_score,
            severity             = excluded.severity,
            classification       = excluded.classification,
            total_runs           = excluded.total_runs,
            failure_count        = excluded.failure_count,
            flaky_failures       = excluded.flaky_failures,
            consecutive_failures = excluded.consecutive_failures,
            last_updated         = excluded.last_updated
    """

    synced = 0
    for row in rows:
        params = [
            row['check_name'], row['job_name'],      row['workflow_name'],
            row['flakiness_score'], row['severity'], row['classification'],
            row['total_runs'],  row['failure_count'], row['flaky_failures'],
            row['consecutive_failures'], row['last_updated'],
        ]
        _d1_query(account_id, db_id, token, sql, params)
        synced += 1

    print(f'[sync] flakiness_scores: synced {synced} rows.', file=sys.stderr)


def sync_run_history(conn, account_id, db_id, token, run_id):
    rows = conn.execute(
        'SELECT * FROM ci_run_history WHERE workflow_run_id = ?', (run_id,)
    ).fetchall()
    if not rows:
        print(f'[sync] ci_run_history: no rows for run {run_id}.', file=sys.stderr)
        return

    sql = """
        INSERT OR IGNORE INTO ci_run_history
            (check_name, job_name, workflow_name, workflow_run_id, run_attempt,
             status, conclusion_category, commit_sha, pr_number, repo, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    synced = 0
    for row in rows:
        params = [
            row['check_name'],  row['job_name'],      row['workflow_name'],
            row['workflow_run_id'], row['run_attempt'],
            row['status'],      row['conclusion_category'],
            row['commit_sha'],  row['pr_number'],
            row['repo'],        row['timestamp'],
        ]
        _d1_query(account_id, db_id, token, sql, params)
        synced += 1

    print(f'[sync] ci_run_history: synced {synced} rows for run {run_id}.', file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description='Sync flakiness data to Cloudflare D1')
    parser.add_argument('--account-id',   default=os.environ.get('CLOUDFLARE_ACCOUNT_ID'))
    parser.add_argument('--database-id',  default=os.environ.get('CLOUDFLARE_D1_DATABASE_ID'))
    parser.add_argument('--token',        default=os.environ.get('CLOUDFLARE_API_TOKEN'))
    parser.add_argument('--workflow-run-id', type=int, default=None,
                        help='Sync ci_run_history only for this run ID')
    parser.add_argument('--db-path', default=None)
    args = parser.parse_args()

    missing = [
        name for name, val in [
            ('--account-id',  args.account_id),
            ('--database-id', args.database_id),
            ('--token',       args.token),
        ]
        if not val
    ]
    if missing:
        print(f'[sync] Missing credentials: {missing}. Skipping D1 sync.', file=sys.stderr)
        return 0

    conn = get_db_connection(args.db_path)

    sync_flakiness_scores(conn, args.account_id, args.database_id, args.token)

    if args.workflow_run_id:
        sync_run_history(conn, args.account_id, args.database_id,
                         args.token, args.workflow_run_id)

    conn.close()
    print('[sync] D1 sync complete.', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
