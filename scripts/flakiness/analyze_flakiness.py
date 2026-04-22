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
    elif failure_rate >= flaky_min and flaky_count > 0:
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
    parser.add_argument('--dry-run', action='store_true',
                        help='Use synthetic 20-run history, skip all D1 calls')
    args = parser.parse_args()

    config = load_config()
    report = {'flaky': [], 'deterministic': [], 'stable': []}

    if args.dry_run:
        print('[dry-run] Dry run enabled — using synthetic 20-run history, skipping D1',
              file=sys.stderr)

        def _p():
            return {'status': 'pass', 'conclusion_category': 'pass'}

        def _f():
            return {'status': 'fail', 'conclusion_category': 'test_failure'}

        # test-suite:        17 pass + 3 fail (scattered) → 15% → flaky/low
        # build:             20 pass → 0% → stable
        # integration-tests: 18 pass + 2 fail (scattered) → 10% → flaky/low
        synthetic = [
            {
                'check_name': 'test-suite', 'job_name': 'test-suite',
                'workflow_name': 'PR Validation',
                'history': (
                    [_p()] * 6 + [_f()] + [_p()] * 4 + [_f()] + [_p()] * 5 + [_f()] + [_p()] * 2
                ),
            },
            {
                'check_name': 'build', 'job_name': 'build',
                'workflow_name': 'PR Validation',
                'history': [_p()] * 20,
            },
            {
                'check_name': 'integration-tests', 'job_name': 'integration-tests',
                'workflow_name': 'PR Validation',
                'history': [_p()] * 9 + [_f()] + [_p()] * 9 + [_f()],
            },
        ]

        for combo in synthetic:
            if args.check_name and combo['check_name'] != args.check_name:
                continue
            check_name    = combo['check_name']
            job_name      = combo['job_name']
            workflow_name = combo['workflow_name']
            history       = combo['history']

            print(f'[dry-run] Analyzing {len(history)} runs for {check_name!r}',
                  file=sys.stderr)
            result = analyze_check(history, config)
            if result is None:
                print(f'[dry-run]   → insufficient data (need ≥5 runs)', file=sys.stderr)
                continue

            score_pct = f'{result["flakiness_score"]:.0%}' if result['flakiness_score'] else '0%'
            print(
                f'[dry-run]   {check_name} \u2192 {result["classification"]} '
                f'(score={score_pct}, severity={result["severity"]})',
                file=sys.stderr,
            )
            print(f'[dry-run]   Skipping D1 upsert for {check_name!r}', file=sys.stderr)

            entry = {'repo': args.repo, 'check_name': check_name,
                     'job_name': job_name, 'workflow_name': workflow_name,
                     **result}
            report[result['classification']].append(entry)

        n_flaky = len(report['flaky'])
        n_det   = len(report['deterministic'])
        n_stab  = len(report['stable'])
        total   = n_flaky + n_det + n_stab
        print(
            f'[dry-run] Flakiness score computed for {total} checks '
            f'({n_flaky} flaky, {n_det} deterministic, {n_stab} stable)',
            file=sys.stderr,
        )

    else:
        account_id, db_id, token = get_d1_credentials()

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

        for combo in combos:
            check_name    = combo['check_name']
            job_name      = combo['job_name']
            workflow_name = combo['workflow_name']

            history = d1_select(
                account_id, db_id, token,
                """
                SELECT status, conclusion_category
                FROM ci_run_history
                WHERE repo = ? AND check_name = ? AND job_name = ? AND workflow_name = ?
                ORDER BY timestamp ASC
                """,
                [args.repo, check_name, job_name, workflow_name],
            )

            result = analyze_check(history, config)
            if result is None:
                continue

            d1_query(
                account_id, db_id, token,
                """
                INSERT INTO flakiness_scores
                    (repo, workflow_name, check_name, job_name, flakiness_score, severity,
                     classification, total_runs, failure_count, flaky_failures,
                     consecutive_failures, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(repo, workflow_name, check_name, job_name) DO UPDATE SET
                    repo                 = excluded.repo,
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
                    args.repo, workflow_name, check_name, job_name,
                    result['flakiness_score'], result['severity'],
                    result['classification'], result['total_runs'],
                    result['failure_count'], result['flaky_failures'],
                    result['consecutive_failures'],
                ],
            )

            entry = {
                'repo':          args.repo,
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
