#!/usr/bin/env python3
"""
Analyze CI run history to detect flaky tests and compute flakiness scores.

Reads from ci_run_history in Cloudflare D1, upserts results into
flakiness_scores, and outputs a JSON report to stdout:
  {
    "flaky":         [{"check_name": ..., "flakiness_score": ..., "severity": ..., ...}],
    "deterministic": [...],
    "stable":        [...]
  }

Usage:
  python analyze_flakiness.py --repo owner/repo [--check-name "job name"]
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from db_utils import get_d1_credentials, d1_query, d1_select, load_config


def _get_severity(score, config):
    """Map a flakiness score (0–1) to a severity label using configured bands."""
    sev = config.get('severity', {})
    low_band    = sev.get('low',    [0.10, 0.20])
    medium_band = sev.get('medium', [0.20, 0.40])

    if score < low_band[0]:
        return 'stable'
    if score < medium_band[0]:
        return 'low'
    if score < medium_band[1]:
        return 'medium'
    return 'high'


def analyze_check(rows, config):
    """
    Classify a single (check_name, job_name) pair given its ordered run history.

    Returns a dict with classification, score, severity, and stats,
    or None if there are insufficient runs.

    Classification rules (in priority order):
      1. < min_runs total non-infra runs          → None (skip)
      2. Last N consecutive failures              → deterministic
      3. failure_rate > flaky_max_rate            → deterministic
      4. flaky_min_rate <= failure_rate <= max    → flaky
      5. Otherwise                                → stable
    """
    thresholds = config.get('thresholds', {})
    window        = thresholds.get('window_size', 20)
    min_runs      = thresholds.get('min_runs', 5)
    flaky_min     = thresholds.get('flaky_min_rate', 0.10)
    flaky_max     = thresholds.get('flaky_max_rate', 0.60)
    consec_det    = thresholds.get('consecutive_failures_deterministic', 3)

    # Only count non-infrastructure runs toward the analysis window
    relevant = [r for r in rows if r['conclusion_category'] != 'infrastructure']
    # Take the most recent `window` runs
    window_rows = relevant[-window:]
    total = len(window_rows)

    if total < min_runs:
        return None

    failures     = [r for r in window_rows if r['status'] == 'fail']
    flaky_confs  = [r for r in window_rows if r['conclusion_category'] == 'flake_confirmed']
    failure_count = len(failures)
    flaky_count   = len(flaky_confs)
    failure_rate  = failure_count / total

    # Count consecutive failures from the most recent end (leading streak)
    consecutive = 0
    for r in reversed(window_rows):
        if r['status'] == 'fail' and r['conclusion_category'] == 'test_failure':
            consecutive += 1
        else:
            break

    # Classify
    if consecutive >= consec_det:
        classification = 'deterministic'
    elif failure_rate > flaky_max:
        classification = 'deterministic'
    elif failure_rate >= flaky_min:
        classification = 'flaky'
    else:
        classification = 'stable'

    # Flakiness score: proportion of failures in the window
    # (only meaningful for flaky checks; set to 0 for stable/deterministic)
    if classification == 'flaky':
        flakiness_score = round(failure_rate, 4)
        severity = _get_severity(flakiness_score, config)
    else:
        flakiness_score = 0.0
        severity = classification  # 'stable' or 'deterministic'

    return {
        'classification':     classification,
        'flakiness_score':    flakiness_score,
        'severity':           severity,
        'total_runs':         total,
        'failure_count':      failure_count,
        'flaky_failures':     flaky_count,
        'consecutive_failures': consecutive,
    }


def main():
    parser = argparse.ArgumentParser(description='Analyze flakiness from CI run history')
    parser.add_argument('--repo', required=True, help='owner/repo')
    parser.add_argument('--check-name', default=None,
                        help='Limit analysis to a single check name')
    args = parser.parse_args()

    account_id, db_id, token = get_d1_credentials()
    config = load_config()

    # Distinct (check_name, job_name, workflow_name) combos for this repo
    base_sql = """
        SELECT DISTINCT check_name, job_name, workflow_name
        FROM ci_run_history
        WHERE repo = ?
    """
    params = [args.repo]
    if args.check_name:
        base_sql += ' AND check_name = ?'
        params.append(args.check_name)

    combos = d1_select(account_id, db_id, token, base_sql, params)

    report = {'flaky': [], 'deterministic': [], 'stable': []}

    for combo in combos:
        check_name    = combo['check_name']
        job_name      = combo['job_name']
        workflow_name = combo['workflow_name']

        # Fetch full ordered history for this combo
        history = d1_select(
            account_id, db_id, token,
            """
            SELECT status, conclusion_category
            FROM ci_run_history
            WHERE repo = ? AND check_name = ? AND job_name = ?
            ORDER BY timestamp ASC
            """,
            [args.repo, check_name, job_name],
        )

        result = analyze_check(history, config)
        if result is None:
            continue  # not enough data yet

        # Upsert into flakiness_scores
        d1_query(
            account_id, db_id, token,
            """
            INSERT INTO flakiness_scores
                (check_name, job_name, workflow_name, flakiness_score, severity,
                 classification, total_runs, failure_count, flaky_failures,
                 consecutive_failures, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
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
            """,
            [
                check_name, job_name, workflow_name,
                result['flakiness_score'], result['severity'],
                result['classification'], result['total_runs'],
                result['failure_count'], result['flaky_failures'],
                result['consecutive_failures'],
            ],
        )

        entry = {
            'check_name':    check_name,
            'job_name':      job_name,
            'workflow_name': workflow_name,
            **result,
        }
        report[result['classification']].append(entry)

    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
