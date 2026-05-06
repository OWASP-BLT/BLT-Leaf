#!/usr/bin/env python3
"""
Collect CI job results from a GitHub Actions workflow run and write them to
Cloudflare D1 via the REST API.

Outputs JSON to stdout:
  {
    "failed_jobs": ["job_name", ...],
    "run_attempt": 1,
    "workflow_name": "CI",
    "all_jobs": [{"check_name": ..., "status": ..., "conclusion_category": ...}, ...]
  }

Usage:
  python collect_ci_results.py \\
      --workflow-run-id 12345678 \\
      --repo owner/repo \\
      --github-token ghp_... \\
      [--commit-sha abc123] \\
      [--pr-number 42] \\
      [--dry-run]
"""

import argparse
import json
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(__file__))
from db_utils import get_d1_credentials, get_infra_patterns, load_config, d1_query

GITHUB_API = 'https://api.github.com'


def _gh_headers(token):
    headers = {
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'BLT-Leaf-Flakiness/1.0',
        'X-GitHub-Api-Version': '2022-11-28',
    }
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return headers


def fetch_run_meta(owner, repo, run_id, token):
    url = f'{GITHUB_API}/repos/{owner}/{repo}/actions/runs/{run_id}'
    resp = requests.get(url, headers=_gh_headers(token), timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_jobs(owner, repo, run_id, token):
    """Fetch all jobs for a run, following pagination."""
    url = f'{GITHUB_API}/repos/{owner}/{repo}/actions/runs/{run_id}/jobs'
    jobs = []
    while url:
        resp = requests.get(url, headers=_gh_headers(token), timeout=30)
        resp.raise_for_status()
        data = resp.json()
        jobs.extend(data.get('jobs', []))
        url = resp.links.get('next', {}).get('url')
    return jobs


def classify_conclusion(job, infra_patterns):
    """
    Map a job's conclusion to a conclusion_category:
      'pass' | 'skip' | 'infrastructure' | 'test_failure'
    """
    conclusion = (job.get('conclusion') or '').lower()

    if conclusion in ('skipped', 'cancelled', 'neutral'):
        return 'skip'

    if conclusion == 'success':
        return 'pass'

    # timed_out is always infrastructure regardless of logs
    if conclusion == 'timed_out':
        return 'infrastructure'

    if conclusion == 'failure':
        # Build a text blob from job name + all step names/conclusions for pattern matching
        step_text = ' '.join(
            f"{s.get('name', '')} {s.get('conclusion') or ''}"
            for s in job.get('steps', [])
        ).lower()
        full_text = f"{job.get('name', '').lower()} {conclusion} {step_text}"

        for pattern in infra_patterns:
            if pattern in full_text:
                return 'infrastructure'
        return 'test_failure'

    # unknown conclusions (e.g. 'action_required') → treat as pass
    return 'pass'


def main():
    parser = argparse.ArgumentParser(description='Collect CI results for a workflow run')
    parser.add_argument('--workflow-run-id', required=True, type=int)
    parser.add_argument('--repo', required=True, help='owner/repo')
    parser.add_argument('--github-token', default=os.environ.get('GITHUB_TOKEN'))
    parser.add_argument('--commit-sha', default='')
    parser.add_argument('--pr-number', type=int, default=None)
    parser.add_argument('--dry-run', action='store_true',
                        help='Parse and print results without writing to DB')
    args = parser.parse_args()

    owner, repo_name = args.repo.split('/', 1)

    if args.dry_run:
        print('[dry-run] Dry run enabled — using synthetic data, skipping all external calls',
              file=sys.stderr)
        config         = load_config()
        infra_patterns = ['econnreset', 'timed_out', 'timeout', 'rate limit',
                          'etimedout', 'fetch failed', 'network error']
        run_attempt    = 1
        workflow_name  = 'PR Validation'
        commit_sha     = args.commit_sha or 'abc123deadbeef'
        jobs = [
            {'name': 'test-suite',        'conclusion': 'failure',
             'steps': [{'name': 'Run tests', 'conclusion': 'failure'}]},
            {'name': 'build',             'conclusion': 'success', 'steps': []},
            {'name': 'lint',              'conclusion': 'success', 'steps': []},
            {'name': 'type-check',        'conclusion': 'success', 'steps': []},
            {'name': 'integration-tests', 'conclusion': 'success', 'steps': []},
            {'name': 'deploy-preview',    'conclusion': 'success', 'steps': []},
        ]
    else:
        account_id, db_id, token = get_d1_credentials()
        infra_patterns = get_infra_patterns(account_id, db_id, token)
        config = load_config()
        run_meta      = fetch_run_meta(owner, repo_name, args.workflow_run_id, args.github_token)
        run_attempt   = run_meta.get('run_attempt', 1)
        workflow_name = run_meta.get('name', 'unknown')
        commit_sha    = args.commit_sha or run_meta.get('head_sha', '')
        jobs = fetch_jobs(owner, repo_name, args.workflow_run_id, args.github_token)

    rows = []
    failed_jobs = []

    for job in jobs:
        conclusion_category = classify_conclusion(job, infra_patterns)
        if conclusion_category in ('pass',):
            status = 'pass'
        elif conclusion_category == 'skip':
            status = 'skip'
        else:
            status = 'fail'

        row = {
            'check_name': job['name'],
            'job_name': job['name'],
            'workflow_name': workflow_name,
            'workflow_run_id': args.workflow_run_id,
            'run_attempt': run_attempt,
            'status': status,
            'conclusion_category': conclusion_category,
            'commit_sha': commit_sha,
            'pr_number': args.pr_number,
            'repo': args.repo,
        }
        rows.append(row)

        if status == 'fail' and conclusion_category == 'test_failure':
            failed_jobs.append(job['name'])

    if not args.dry_run:
        insert_sql = """
            INSERT INTO ci_run_history
                (check_name, job_name, workflow_name, workflow_run_id, run_attempt,
                 status, conclusion_category, commit_sha, pr_number, repo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        for row in rows:
            d1_query(
                account_id, db_id, token,
                insert_sql,
                [
                    row['check_name'], row['job_name'], row['workflow_name'],
                    row['workflow_run_id'], row['run_attempt'], row['status'],
                    row['conclusion_category'], row['commit_sha'],
                    row['pr_number'], row['repo'],
                ],
            )

        # Prune history older than configured retention window
        prune_days = config.get('github', {}).get('history_prune_days', 90)
        d1_query(
            account_id, db_id, token,
            "DELETE FROM ci_run_history WHERE timestamp < datetime('now', ?)",
            [f'-{prune_days} days'],
        )
    else:
        print(f'[dry-run] Collected {len(rows)} CI jobs '
              f'({len(failed_jobs)} test failure(s)) — skipping D1 writes',
              file=sys.stderr)
        for r in rows:
            icon = '\u2713' if r['status'] == 'pass' else '\u2717'
            print(f'[dry-run]   {icon} {r["job_name"]:30s}  {r["conclusion_category"]}',
                  file=sys.stderr)

    output = {
        'failed_jobs': failed_jobs,
        'run_attempt': run_attempt,
        'workflow_name': workflow_name,
        'all_jobs': rows,
    }
    print(json.dumps(output))
    return 0


if __name__ == '__main__':
    sys.exit(main())
