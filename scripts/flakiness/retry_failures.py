#!/usr/bin/env python3
"""
Actively retry failed CI jobs when the current run is the first attempt.

- If run_attempt > 1: skip re-triggering (already retried), report as-is.
- If run_attempt == 1: call rerun-failed-jobs, poll for completion, then
  check which previously-failed jobs now passed and mark them as flake_confirmed.

Reads collect_ci_results.py output from --collect-output file or stdin.

Outputs JSON to stdout:
  {
    "job_name": "confirmed_flake" | "real_failure" | "skipped_already_retried" |
                "rerun_not_permitted" | "poll_timeout",
    ...
  }

Usage:
  python retry_failures.py \\
      --workflow-run-id 12345678 \\
      --repo owner/repo \\
      --github-token ghp_... \\
      --collect-output /tmp/collect_output.json
"""

import argparse
import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(__file__))
from db_utils import get_d1_credentials, d1_query

GITHUB_API      = 'https://api.github.com'
POLL_INTERVAL_S = 30    # seconds between status polls
MAX_POLL_S      = 600   # 10-minute maximum wait


def _gh_headers(token):
    headers = {
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'BLT-Leaf-Flakiness/1.0',
        'X-GitHub-Api-Version': '2022-11-28',
    }
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return headers


def trigger_rerun(owner, repo, run_id, token):
    """POST rerun-failed-jobs. Returns True if triggered, False if not permitted."""
    url = f'{GITHUB_API}/repos/{owner}/{repo}/actions/runs/{run_id}/rerun-failed-jobs'
    resp = requests.post(url, headers=_gh_headers(token), timeout=30)
    if resp.status_code == 403:
        print('[retry] No permission to trigger rerun (403). Skipping.', file=sys.stderr)
        return False
    resp.raise_for_status()
    return True


def poll_run_completion(owner, repo, run_id, token):
    """
    Poll the run status until it completes or timeout is reached.
    Returns (conclusion, new_run_attempt) or (None, None) on timeout.
    """
    url = f'{GITHUB_API}/repos/{owner}/{repo}/actions/runs/{run_id}'
    deadline = time.monotonic() + MAX_POLL_S

    while time.monotonic() < deadline:
        resp = requests.get(url, headers=_gh_headers(token), timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get('status') == 'completed':
            return data.get('conclusion'), data.get('run_attempt', 1)
        print(f'[retry] Run {run_id} status={data.get("status")!r}, '
              f'waiting {POLL_INTERVAL_S}s…', file=sys.stderr)
        time.sleep(POLL_INTERVAL_S)

    print(f'[retry] Timed out waiting for run {run_id}.', file=sys.stderr)
    return None, None


def fetch_job_conclusions(owner, repo, run_id, token):
    """Return {job_name: conclusion} for the latest attempt of each job."""
    url = f'{GITHUB_API}/repos/{owner}/{repo}/actions/runs/{run_id}/jobs'
    conclusions = {}
    while url:
        resp = requests.get(url, headers=_gh_headers(token), timeout=30)
        resp.raise_for_status()
        data = resp.json()
        for job in data.get('jobs', []):
            conclusions[job['name']] = job.get('conclusion', 'unknown')
        url = resp.links.get('next', {}).get('url')
    return conclusions


def mark_flake_confirmed(account_id, db_id, token, workflow_run_id, job_name, repo, new_attempt):
    """
    Insert a flake_confirmed row by copying the original failure row's metadata
    and recording the rerun as a passing attempt.
    """
    d1_query(
        account_id, db_id, token,
        """
        INSERT INTO ci_run_history
            (check_name, job_name, workflow_name, workflow_run_id, run_attempt,
             status, conclusion_category, commit_sha, pr_number, repo)
        SELECT check_name, job_name, workflow_name, ?, ?,
               'pass', 'flake_confirmed', commit_sha, pr_number, repo
        FROM ci_run_history
        WHERE workflow_run_id = ? AND job_name = ? AND repo = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        [workflow_run_id, new_attempt, workflow_run_id, job_name, repo],
    )


def main():
    parser = argparse.ArgumentParser(
        description='Retry failed CI jobs and classify results as flake or real failure'
    )
    parser.add_argument('--workflow-run-id', required=True, type=int)
    parser.add_argument('--repo', required=True, help='owner/repo')
    parser.add_argument('--github-token', default=os.environ.get('GITHUB_TOKEN'))
    parser.add_argument('--collect-output', default=None,
                        help='Path to JSON file from collect_ci_results.py; '
                             'reads stdin if omitted')
    parser.add_argument('--dry-run', action='store_true',
                        help='Simulate retry without any GitHub or D1 calls')
    args = parser.parse_args()

    if args.collect_output:
        with open(args.collect_output, encoding='utf-8-sig') as fh:
            collect_data = json.load(fh)
    else:
        collect_data = json.loads(sys.stdin.read())

    failed_jobs = collect_data.get('failed_jobs', [])
    run_attempt = collect_data.get('run_attempt', 1)
    result = {}

    if not failed_jobs:
        print(json.dumps(result))
        return 0

    # --- Dry-run: simulate the retry without touching GitHub or D1 ---
    if args.dry_run:
        print('[dry-run] Dry run enabled — simulating retry, skipping GitHub/D1 calls',
              file=sys.stderr)
        if run_attempt > 1:
            print(f'[dry-run] run_attempt={run_attempt} — already retried, skipping.',
                  file=sys.stderr)
            for job in failed_jobs:
                result[job] = 'skipped_already_retried'
        else:
            print(f'[dry-run] Simulating rerun-failed-jobs for run '
                  f'{args.workflow_run_id}…', file=sys.stderr)
            for job in failed_jobs:
                print(f'[retry] Retrying failed job: {job}', file=sys.stderr)
                print('[retry] Simulated retry result: success', file=sys.stderr)
                result[job] = 'confirmed_flake'
                print(f'[retry] Marked as flaky: {job!r} (passed on retry — '
                      'skipping D1 write)', file=sys.stderr)
            n_flakes = len([v for v in result.values() if v == 'confirmed_flake'])
            print(f'[dry-run] {n_flakes} flaky job(s) confirmed', file=sys.stderr)
        print(json.dumps(result))
        return 0

    # If this is already a retry run, skip re-triggering
    if run_attempt > 1:
        print(f'[retry] run_attempt={run_attempt} — already retried. '
              'Skipping re-trigger.', file=sys.stderr)
        for job in failed_jobs:
            result[job] = 'skipped_already_retried'
        print(json.dumps(result))
        return 0

    if '/' not in args.repo:
        print(f"Error: --repo must be in 'owner/repo' format, got '{args.repo}'", file=sys.stderr)
        for job in failed_jobs:
            result[job] = 'malformed_repo_arg'
        print(json.dumps(result))
        return 1
    owner, repo_name = args.repo.split('/', 1)
    account_id, db_id, token = get_d1_credentials()

    print(f'[retry] Triggering rerun-failed-jobs for run '
          f'{args.workflow_run_id}…', file=sys.stderr)
    triggered = trigger_rerun(owner, repo_name, args.workflow_run_id, args.github_token)

    if not triggered:
        for job in failed_jobs:
            result[job] = 'rerun_not_permitted'
        print(json.dumps(result))
        return 0

    _, new_attempt = poll_run_completion(
        owner, repo_name, args.workflow_run_id, args.github_token
    )

    if new_attempt is None:
        for job in failed_jobs:
            result[job] = 'poll_timeout'
        print(json.dumps(result))
        return 0

    # Compare per-job outcomes from the rerun
    job_conclusions = fetch_job_conclusions(
        owner, repo_name, args.workflow_run_id, args.github_token
    )

    for job in failed_jobs:
        rerun_conclusion = job_conclusions.get(job, 'unknown')
        if rerun_conclusion == 'success':
            result[job] = 'confirmed_flake'
            mark_flake_confirmed(account_id, db_id, token, args.workflow_run_id, job, args.repo, new_attempt)
            print(f'[retry] {job!r}: confirmed flake (passed on retry)', file=sys.stderr)
        else:
            result[job] = 'real_failure'
            print(f'[retry] {job!r}: real failure (failed again on retry)', file=sys.stderr)
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
