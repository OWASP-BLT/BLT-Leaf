"""Tests for report_flakiness.py — report builders and main() integration."""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import db_utils
from report_flakiness import _build_issue_body, _build_markdown_report, main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _entry(
    check_name='lint',
    job_name='lint',
    workflow_name='CI',
    score=0.25,
    severity='medium',
    classification='flaky',
    total=10,
    failures=3,
    flaky=2,
    consecutive=0,
    last_updated='2026-03-11',
):
    return {
        'check_name': check_name,
        'job_name': job_name,
        'workflow_name': workflow_name,
        'flakiness_score': score,
        'severity': severity,
        'classification': classification,
        'total_runs': total,
        'failure_count': failures,
        'flaky_failures': flaky,
        'consecutive_failures': consecutive,
        'last_updated': last_updated,
    }


# ---------------------------------------------------------------------------
# _build_issue_body
# ---------------------------------------------------------------------------
class TestBuildIssueBody(unittest.TestCase):
    def test_contains_check_name(self):
        self.assertIn('my-check', _build_issue_body(_entry(check_name='my-check')))

    def test_contains_severity(self):
        self.assertIn('high', _build_issue_body(_entry(severity='high')))

    def test_contains_classification(self):
        self.assertIn('flaky', _build_issue_body(_entry(classification='flaky')))

    def test_score_rendered_as_percentage(self):
        body = _build_issue_body(_entry(score=0.25))
        self.assertIn('25.00%', body)

    def test_total_runs_and_failure_count_present(self):
        body = _build_issue_body(_entry(total=20, failures=5))
        self.assertIn('20', body)
        self.assertIn('5', body)

    def test_failure_rate_computed_correctly(self):
        body = _build_issue_body(_entry(total=10, failures=3))
        self.assertIn('30.0%', body)

    def test_zero_total_does_not_raise_and_shows_na(self):
        body = _build_issue_body(_entry(total=0, failures=0))
        self.assertIn('N/A', body)

    def test_contains_nextg_steps_section(self):
        body = _build_issue_body(_entry())
        self.assertIn('Next steps', body)


# ---------------------------------------------------------------------------
# _build_markdown_report
# ---------------------------------------------------------------------------
class TestBuildMarkdownReport(unittest.TestCase):
    def _scores(self):
        return [
            _entry('check-a', score=0.30, classification='flaky', severity='medium'),
            _entry('check-b', score=0.0, classification='deterministic',
                   severity='deterministic', consecutive=5),
            _entry('check-c', score=0.0, classification='stable', severity='stable'),
        ]

    def test_contains_repo_name(self):
        self.assertIn('owner/repo', _build_markdown_report(self._scores(), 'owner/repo'))

    def test_contains_summary_section(self):
        self.assertIn('Summary', _build_markdown_report(self._scores(), 'owner/repo'))

    def test_flaky_count_in_summary_table(self):
        report = _build_markdown_report(self._scores(), 'owner/repo')
        self.assertIn('| Flaky | 1 |', report)

    def test_deterministic_count_in_summary_table(self):
        report = _build_markdown_report(self._scores(), 'owner/repo')
        self.assertIn('| Deterministic failures | 1 |', report)

    def test_stable_count_in_summary_table(self):
        report = _build_markdown_report(self._scores(), 'owner/repo')
        self.assertIn('| Stable | 1 |', report)

    def test_flaky_check_name_appears_in_report(self):
        report = _build_markdown_report(self._scores(), 'owner/repo')
        self.assertIn('check-a', report)

    def test_empty_scores_shows_no_flaky_placeholder(self):
        report = _build_markdown_report([], 'owner/repo')
        self.assertIn('_No flaky tests detected._', report)

    def test_flaky_checks_sorted_by_score_descending(self):
        scores = [
            _entry('low-check', score=0.15, classification='flaky', severity='low'),
            _entry('high-check', score=0.45, classification='flaky', severity='high'),
        ]
        report = _build_markdown_report(scores, 'repo')
        high_pos = report.index('high-check')
        low_pos = report.index('low-check')
        self.assertLess(high_pos, low_pos)


# ---------------------------------------------------------------------------
# main() integration
# ---------------------------------------------------------------------------
class TestReportMain(unittest.TestCase):
    def setUp(self):
        db_utils._config_cache = None

    def tearDown(self):
        db_utils._config_cache = None

    def _make_flaky_entry(self):
        return _entry('lint', score=0.25, classification='flaky')

    def _make_flaky_report(self):
        return {
            'flaky': [self._make_flaky_entry()],
            'deterministic': [],
            'stable': [],
        }

    @patch('report_flakiness.d1_select')
    @patch('report_flakiness.get_d1_credentials')
    @patch('report_flakiness.requests.get')
    @patch('report_flakiness.requests.post')
    def test_main_writes_markdown_and_metrics_files(
        self, mock_post, mock_get, mock_creds, mock_select
    ):
        mock_creds.return_value = ('acct', 'db', 'tok')
        mock_select.return_value = [self._make_flaky_entry()]

        # GitHub issue search returns no existing issue → will create one
        search_resp = MagicMock()
        search_resp.status_code = 200
        search_resp.json.return_value = {'items': []}
        mock_get.return_value = search_resp

        create_resp = MagicMock()
        create_resp.raise_for_status = MagicMock()
        create_resp.json.return_value = {'number': 1, 'state': 'open'}
        mock_post.return_value = create_resp

        with tempfile.TemporaryDirectory() as tmpdir:
            report_file = os.path.join(tmpdir, 'flaky_report.json')
            with open(report_file, 'w') as fh:
                json.dump(self._make_flaky_report(), fh)

            with patch('report_flakiness.DATA_DIR', tmpdir):
                with patch('sys.argv', [
                    'report_flakiness.py',
                    '--repo', 'owner/repo',
                    '--github-token', 'tok',
                    '--flaky-report', report_file,
                ]):
                    main()

            self.assertTrue(
                os.path.exists(os.path.join(tmpdir, 'flakiness_report.md'))
            )
            self.assertTrue(
                os.path.exists(os.path.join(tmpdir, 'flakiness_metrics.json'))
            )

    @patch('report_flakiness.d1_select')
    @patch('report_flakiness.get_d1_credentials')
    @patch('report_flakiness.requests.get')
    @patch('report_flakiness.requests.post')
    def test_metrics_json_has_expected_structure(
        self, mock_post, mock_get, mock_creds, mock_select
    ):
        mock_creds.return_value = ('acct', 'db', 'tok')
        mock_select.return_value = [self._make_flaky_entry()]

        search_resp = MagicMock()
        search_resp.status_code = 200
        search_resp.json.return_value = {'items': []}
        mock_get.return_value = search_resp

        create_resp = MagicMock()
        create_resp.raise_for_status = MagicMock()
        create_resp.json.return_value = {'number': 1}
        mock_post.return_value = create_resp

        with tempfile.TemporaryDirectory() as tmpdir:
            report_file = os.path.join(tmpdir, 'flaky_report.json')
            with open(report_file, 'w') as fh:
                json.dump(self._make_flaky_report(), fh)

            with patch('report_flakiness.DATA_DIR', tmpdir):
                with patch('sys.argv', [
                    'report_flakiness.py',
                    '--repo', 'owner/repo',
                    '--github-token', 'tok',
                    '--flaky-report', report_file,
                ]):
                    main()

            metrics_path = os.path.join(tmpdir, 'flakiness_metrics.json')
            with open(metrics_path) as fh:
                metrics = json.load(fh)

        for key in ('generated_at', 'repo', 'summary', 'scores'):
            self.assertIn(key, metrics)
        for key in ('flaky', 'deterministic', 'stable'):
            self.assertIn(key, metrics['summary'])

    @patch('report_flakiness.d1_select')
    @patch('report_flakiness.get_d1_credentials')
    def test_no_github_flag_skips_all_github_api_calls(self, mock_creds, mock_select):
        mock_creds.return_value = ('acct', 'db', 'tok')
        mock_select.return_value = []

        with tempfile.TemporaryDirectory() as tmpdir:
            report_file = os.path.join(tmpdir, 'flaky_report.json')
            with open(report_file, 'w') as fh:
                json.dump({'flaky': [], 'deterministic': [], 'stable': []}, fh)

            with patch('report_flakiness.DATA_DIR', tmpdir):
                with patch('sys.argv', [
                    'report_flakiness.py',
                    '--repo', 'owner/repo',
                    '--github-token', 'tok',
                    '--flaky-report', report_file,
                    '--no-github',
                ]):
                    with patch('report_flakiness.requests.post') as mock_post:
                        with patch('report_flakiness.requests.get') as mock_get:
                            main()

        mock_post.assert_not_called()
        mock_get.assert_not_called()

    @patch('report_flakiness.d1_select')
    @patch('report_flakiness.get_d1_credentials')
    @patch('report_flakiness.requests.get')
    @patch('report_flakiness.requests.post')
    def test_creates_github_issue_for_new_flaky_check(
        self, mock_post, mock_get, mock_creds, mock_select
    ):
        mock_creds.return_value = ('acct', 'db', 'tok')
        mock_select.return_value = [self._make_flaky_entry()]

        # Search returns no existing issue
        search_resp = MagicMock()
        search_resp.status_code = 200
        search_resp.json.return_value = {'items': []}
        mock_get.return_value = search_resp

        create_resp = MagicMock()
        create_resp.raise_for_status = MagicMock()
        create_resp.json.return_value = {'number': 42}
        mock_post.return_value = create_resp

        with tempfile.TemporaryDirectory() as tmpdir:
            report_file = os.path.join(tmpdir, 'flaky_report.json')
            with open(report_file, 'w') as fh:
                json.dump(self._make_flaky_report(), fh)

            with patch('report_flakiness.DATA_DIR', tmpdir):
                with patch('sys.argv', [
                    'report_flakiness.py',
                    '--repo', 'owner/repo',
                    '--github-token', 'tok',
                    '--flaky-report', report_file,
                ]):
                    main()

        # The first POST creates the issue (not a comment)
        create_call = mock_post.call_args_list[0]
        url = create_call[0][0]
        self.assertIn('/issues', url)
        self.assertNotIn('/comments', url)


if __name__ == '__main__':
    unittest.main()
