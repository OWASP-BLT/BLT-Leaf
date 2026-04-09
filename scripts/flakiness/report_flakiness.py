#!/usr/bin/env python3
"""
Report flakiness results to GitHub and write local report files.

Actions performed:
  1. For each newly flaky check: create / reopen / update a GitHub Issue
     labelled 'flaky-test' and 'ci-instability'.
  2. If --pr-number is given: post a PR comment summarising flaky checks.
  3. Write data/flakiness_report.md  — human-readable summary.
  4. Write data/flakiness_metrics.json — machine-readable metrics.

Reads the flaky report JSON from --flaky-report file or stdin
(output of analyze_flakiness.py).

Usage:
  python report_flakiness.py \\
      --repo owner/repo \\
      --github-token ghp_... \\
      [--pr-number 42] \\
      [--flaky-report /tmp/flaky_report.json] \\
      [--no-github]
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import requests

sys.path.insert(0, os.path.dirname(__file__))
from db_utils import get_d1_credentials, d1_select, load_config

GITHUB_API = 'https://api.github.com'
_REPO_ROOT  = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..'))
DATA_DIR    = os.path.join(_REPO_ROOT, 'data')


def _gh_headers(token):
    headers = {
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'BLT-Leaf-Flakiness/1.0',
        'X-GitHub-Api-Version': '2022-11-28',
    }
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return headers


# ---------------------------------------------------------------------------
# GitHub Issue helpers
# ---------------------------------------------------------------------------

def _check_identity(check_name, job_name, workflow_name):
    check_name    = check_name or 'unknown'
    job_name      = job_name or 'unknown'
    workflow_name = workflow_name or 'unknown'
    return f'{workflow_name} / {job_name} / {check_name}'


def _issue_title(check_name, job_name, workflow_name, prefix):
    return f'{prefix} {_check_identity(check_name, job_name, workflow_name)}'


def search_flaky_issue(owner, repo, check_name, job_name, workflow_name, token, prefix):
    """Return the first matching GitHub issue or None."""
    title = _issue_title(check_name, job_name, workflow_name, prefix)
    query = f'"{title}" repo:{owner}/{repo} is:issue'
    resp = requests.get(
        f'{GITHUB_API}/search/issues',
        params={'q': query, 'per_page': 5},
        headers=_gh_headers(token),
        timeout=30,
    )
    if resp.status_code != 200:
        return None
    items = resp.json().get('items', [])
    return items[0] if items else None


def create_issue(owner, repo, entry, token, config, labels):
    check_name = entry['check_name']
    job_name = entry.get('job_name')
    workflow_name = entry.get('workflow_name')
    prefix     = config.get('github', {}).get('issue_title_prefix', '[Flaky Test]')
    resp = requests.post(
        f'{GITHUB_API}/repos/{owner}/{repo}/issues',
        headers=_gh_headers(token),
        json={
            'title':  _issue_title(check_name, job_name, workflow_name, prefix),
            'body':   _build_issue_body(entry),
            'labels': labels,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def add_issue_comment(owner, repo, issue_number, entry, token):
    resp = requests.post(
        f'{GITHUB_API}/repos/{owner}/{repo}/issues/{issue_number}/comments',
        headers=_gh_headers(token),
        json={'body': _build_issue_body(entry)},
        timeout=30,
    )
    resp.raise_for_status()


def reopen_issue(owner, repo, issue_number, token):
    resp = requests.patch(
        f'{GITHUB_API}/repos/{owner}/{repo}/issues/{issue_number}',
        headers=_gh_headers(token),
        json={'state': 'open'},
        timeout=30,
    )
    resp.raise_for_status()


def _build_issue_body(entry):
    check_name    = entry.get('check_name', 'unknown')
    job_name      = entry.get('job_name', 'unknown')
    workflow_name = entry.get('workflow_name', 'unknown')
    score         = entry.get('flakiness_score', 0.0)
    severity      = entry.get('severity', 'unknown')
    classification = entry.get('classification', 'unknown')
    total         = entry.get('total_runs', 0)
    failures      = entry.get('failure_count', 0)
    flaky         = entry.get('flaky_failures', 0)
    failure_rate  = f'{failures / total:.1%}' if total else 'N/A'
    now           = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    return f"""\
## Flaky CI Check: `{_check_identity(check_name, job_name, workflow_name)}`

**Detected:** {now}
**Workflow:** `{workflow_name}` | **Job:** `{job_name}`
**Classification:** `{classification}` | **Severity:** `{severity}`
**Flakiness Score:** {score:.2%}

### Statistics (last analysis window)

| Metric | Value |
|--------|-------|
| Total runs analysed | {total} |
| Failures | {failures} |
| Confirmed flakes (pass on retry) | {flaky} |
| Failure rate | {failure_rate} |

### What this means
This check is failing **intermittently** without a deterministic code change.
It will **not block merges** while classified as flaky.

### Next steps
- [ ] Investigate the root cause of intermittent failures
- [ ] If environment-dependent, add retry logic inside the test
- [ ] If infrastructure-related, add the log pattern to `known_infrastructure_issues`

---
*Automatically managed by [BLT-Leaf Flakiness Detector](../../scripts/flakiness/).*
"""


# ---------------------------------------------------------------------------
# PR comment
# ---------------------------------------------------------------------------

def post_pr_comment(owner, repo, pr_number, flaky_entries, token):
    if not flaky_entries:
        return
    rows = '\n'.join(
        f'| `{_check_identity(e.get("check_name"), e.get("job_name"), e.get("workflow_name"))}` '
        f'| {e["severity"]} | {e["flakiness_score"]:.2%} '
        f'| {e["failure_count"]}/{e["total_runs"]} |'
        for e in flaky_entries
    )
    body = (
        '## :test_tube: Flaky Tests Detected\n\n'
        'The following CI checks were classified as **flaky** in this run. '
        'They will **not block merge**.\n\n'
        '| Workflow / Job / Check | Severity | Flakiness Score | Failures / Runs |\n'
        '|------------------------|----------|----------------|------------------|\n'
        f'{rows}\n\n'
        '> Flaky checks fail intermittently without a code regression. '
        'Maintainers have been notified via GitHub Issues.'
    )
    resp = requests.post(
        f'{GITHUB_API}/repos/{owner}/{repo}/issues/{pr_number}/comments',
        headers=_gh_headers(token),
        json={'body': body},
        timeout=30,
    )
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# Report file builders
# ---------------------------------------------------------------------------

def _build_markdown_report(all_scores, repo):
    now           = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    flaky         = [s for s in all_scores if s['classification'] == 'flaky']
    deterministic = [s for s in all_scores if s['classification'] == 'deterministic']
    stable        = [s for s in all_scores if s['classification'] == 'stable']

    flaky_sorted = sorted(flaky, key=lambda x: x['flakiness_score'], reverse=True)
    flaky_rows   = '\n'.join(
        f'| `{e["workflow_name"]}` | `{e["job_name"]}` | `{e["check_name"]}` | {e["severity"]} '
        f'| {e["flakiness_score"]:.2%} | {e["failure_count"]}/{e["total_runs"]} '
        f'| {str(e.get("last_updated", ""))[:10]} |'
        for e in flaky_sorted[:20]
    ) or '_No flaky tests detected._'

    det_rows = '\n'.join(
        f'| `{e["workflow_name"]}` | `{e["job_name"]}` | `{e["check_name"]}` '
        f'| {e["consecutive_failures"]} consecutive |'
        for e in deterministic[:10]
    ) or '_None._'

    return f"""\
# Flakiness Report — {repo}

Generated: {now}

## Summary

| Category | Count |
|----------|-------|
| Flaky | {len(flaky)} |
| Deterministic failures | {len(deterministic)} |
| Stable | {len(stable)} |

## Top Flaky Checks

| Workflow | Job | Check | Severity | Score | Failures / Runs | Last Updated |
|----------|-----|-------|----------|-------|-----------------|--------------|
{flaky_rows}

## Deterministic Failures

| Workflow | Job | Check | Evidence |
|----------|-----|-------|----------|
{det_rows}

---
*Managed by BLT-Leaf Flakiness Detector. \
Thresholds: [`scripts/flakiness/flakiness_config.yml`](../scripts/flakiness/flakiness_config.yml)*
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Report flakiness to GitHub and write local report files'
    )
    parser.add_argument('--repo', required=True, help='owner/repo')
    parser.add_argument('--github-token', default=os.environ.get('GITHUB_TOKEN'))
    parser.add_argument('--pr-number', type=int, default=None)
    parser.add_argument('--flaky-report', default=None,
                        help='Path to JSON from analyze_flakiness.py; reads stdin if omitted')
    parser.add_argument('--no-github', action='store_true',
                        help='Skip all GitHub API calls (useful for local testing)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Skip D1 reads and all GitHub calls; write report files only')
    args = parser.parse_args()

    config = load_config()

    if '/' not in args.repo:
        print(f"Error: --repo must be in 'owner/repo' format, got '{args.repo}'", file=sys.stderr)
        return 1
    owner, repo_name = args.repo.split('/', 1)

    if not args.dry_run:
        account_id, db_id, token = get_d1_credentials()

    # Load flaky report
    if args.flaky_report:
        with open(args.flaky_report, encoding='utf-8') as fh:
            report = json.load(fh)
    elif not args.dry_run:
        report = json.loads(sys.stdin.read())
    else:
        # dry-run with no file: use synthetic data
        print('[dry-run] No --flaky-report supplied; using synthetic data', file=sys.stderr)
        report = {
            'flaky': [
                {'check_name': 'test-suite', 'job_name': 'test-suite',
                 'workflow_name': 'PR Validation', 'classification': 'flaky',
                 'flakiness_score': 0.15, 'severity': 'low',
                 'total_runs': 20, 'failure_count': 3, 'flaky_failures': 1,
                 'consecutive_failures': 0},
                {'check_name': 'integration-tests', 'job_name': 'integration-tests',
                 'workflow_name': 'PR Validation', 'classification': 'flaky',
                 'flakiness_score': 0.10, 'severity': 'low',
                 'total_runs': 20, 'failure_count': 2, 'flaky_failures': 1,
                 'consecutive_failures': 0},
            ],
            'deterministic': [],
            'stable': [
                {'check_name': 'build', 'job_name': 'build',
                 'workflow_name': 'PR Validation', 'classification': 'stable',
                 'flakiness_score': 0.0, 'severity': 'stable',
                 'total_runs': 20, 'failure_count': 0, 'flaky_failures': 0,
                 'consecutive_failures': 0},
            ],
        }

    flaky_entries = report.get('flaky', [])
    label_flaky   = config.get('labels', {}).get('flaky_test',     'flaky-test')
    label_infra   = config.get('labels', {}).get('infrastructure', 'ci-instability')
    prefix        = config.get('github', {}).get('issue_title_prefix', '[Flaky Test]')

    # --- GitHub Issue automation ---
    if not args.no_github and not args.dry_run and args.github_token:
        for entry in flaky_entries:
            check_name = entry['check_name']
            job_name = entry.get('job_name')
            workflow_name = entry.get('workflow_name')
            identity = _check_identity(check_name, job_name, workflow_name)
            existing   = search_flaky_issue(
                owner, repo_name, check_name, job_name, workflow_name,
                args.github_token, prefix
            )
            if existing is None:
                create_issue(owner, repo_name, entry, args.github_token,
                             config, [label_flaky, label_infra])
                print(f'[report] Created issue for: {identity}', file=sys.stderr)
            elif existing.get('state') == 'closed':
                reopen_issue(owner, repo_name, existing['number'], args.github_token)
                add_issue_comment(owner, repo_name, existing['number'],
                                  entry, args.github_token)
                print(f'[report] Reopened issue #{existing["number"]} for: {identity}',
                      file=sys.stderr)
            else:
                add_issue_comment(owner, repo_name, existing['number'],
                                  entry, args.github_token)
                print(f'[report] Updated issue #{existing["number"]} for: {identity}',
                      file=sys.stderr)

        # --- PR comment ---
        if (args.pr_number and flaky_entries
                and config.get('github', {}).get('pr_comment_on_flake', True)):
            post_pr_comment(
                owner, repo_name, args.pr_number, flaky_entries, args.github_token
            )
            print(f'[report] Posted PR comment on #{args.pr_number}', file=sys.stderr)

    # --- Write local report files ---
    if args.dry_run:
        print('[dry-run] Dry run enabled — skipping D1 reads, building report from input',
              file=sys.stderr)
        all_scores = (
            report.get('flaky', [])
            + report.get('deterministic', [])
            + report.get('stable', [])
        )
    else:
        all_scores = d1_select(
            account_id, db_id, token,
            'SELECT * FROM flakiness_scores WHERE repo = ? ORDER BY flakiness_score DESC',
            [args.repo],
        )

    os.makedirs(DATA_DIR, exist_ok=True)

    report_path = os.path.join(DATA_DIR, 'flakiness_report.md')
    with open(report_path, 'w', encoding='utf-8') as fh:
        fh.write(_build_markdown_report(all_scores, args.repo))
    print(f'[report] Wrote {report_path}', file=sys.stderr)

    metrics = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'repo':         args.repo,
        'summary': {
            'flaky':         len([s for s in all_scores if s['classification'] == 'flaky']),
            'deterministic': len([s for s in all_scores if s['classification'] == 'deterministic']),
            'stable':        len([s for s in all_scores if s['classification'] == 'stable']),
        },
        'scores': all_scores,
    }
    metrics_path = os.path.join(DATA_DIR, 'flakiness_metrics.json')
    with open(metrics_path, 'w', encoding='utf-8') as fh:
        json.dump(metrics, fh, indent=2)
    print(f'[report] Wrote {metrics_path}', file=sys.stderr)

    return 0


if __name__ == '__main__':
    sys.exit(main())
