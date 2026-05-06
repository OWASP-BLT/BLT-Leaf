"""Tests for collect_ci_results.py — classify_conclusion() and main() integration."""

import json
import os
import sys
import tempfile
import unittest
from io import StringIO
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from collect_ci_results import classify_conclusion, main

_INFRA_PATTERNS = ['econnreset', 'timed_out', 'timeout', 'network error', 'fetch failed']


def _job(conclusion, name='test-job', steps=None):
    return {'name': name, 'conclusion': conclusion, 'steps': steps or []}


def _step(name, conclusion='success'):
    return {'name': name, 'conclusion': conclusion}


# ---------------------------------------------------------------------------
# classify_conclusion
# ---------------------------------------------------------------------------
class TestClassifyConclusion(unittest.TestCase):
    def test_success_is_pass(self):
        self.assertEqual(classify_conclusion(_job('success'), _INFRA_PATTERNS), 'pass')

    def test_skipped_is_skip(self):
        self.assertEqual(classify_conclusion(_job('skipped'), _INFRA_PATTERNS), 'skip')

    def test_cancelled_is_skip(self):
        self.assertEqual(classify_conclusion(_job('cancelled'), _INFRA_PATTERNS), 'skip')

    def test_neutral_is_skip(self):
        self.assertEqual(classify_conclusion(_job('neutral'), _INFRA_PATTERNS), 'skip')

    def test_timed_out_is_always_infrastructure(self):
        self.assertEqual(classify_conclusion(_job('timed_out'), _INFRA_PATTERNS), 'infrastructure')

    def test_failure_with_infra_pattern_in_step_name(self):
        steps = [_step('Install deps — fetch failed happened', 'failure')]
        self.assertEqual(
            classify_conclusion(_job('failure', steps=steps), _INFRA_PATTERNS),
            'infrastructure',
        )

    def test_failure_with_econnreset_in_step(self):
        steps = [_step('Run tests (ECONNRESET)', 'failure')]
        self.assertEqual(
            classify_conclusion(_job('failure', steps=steps), _INFRA_PATTERNS),
            'infrastructure',
        )

    def test_failure_with_network_error_in_job_name(self):
        job = _job('failure', name='network error prone job')
        self.assertEqual(classify_conclusion(job, _INFRA_PATTERNS), 'infrastructure')

    def test_failure_without_infra_pattern_is_test_failure(self):
        steps = [_step('Run unit tests', 'failure')]
        self.assertEqual(
            classify_conclusion(_job('failure', steps=steps), _INFRA_PATTERNS),
            'test_failure',
        )

    def test_failure_with_no_steps_is_test_failure(self):
        self.assertEqual(classify_conclusion(_job('failure'), _INFRA_PATTERNS), 'test_failure')

    def test_unknown_conclusion_treated_as_pass(self):
        self.assertEqual(
            classify_conclusion(_job('action_required'), _INFRA_PATTERNS), 'pass'
        )

    def test_empty_infra_patterns_makes_all_failures_test_failure(self):
        steps = [_step('timeout step', 'failure')]
        self.assertEqual(
            classify_conclusion(_job('failure', steps=steps), []),
            'test_failure',
        )

    def test_case_insensitive_pattern_matching(self):
        # Pattern stored lowercase, job conclusion text is lowercased before matching
        steps = [_step('NETWORK ERROR in step', 'failure')]
        self.assertEqual(
            classify_conclusion(_job('failure', steps=steps), _INFRA_PATTERNS),
            'infrastructure',
        )


# ---------------------------------------------------------------------------
# main() integration
# ---------------------------------------------------------------------------
class TestCollectMain(unittest.TestCase):
    def setUp(self):
        self._mock_run_meta = {
            'run_attempt': 1,
            'name': 'PR Validation',
            'head_sha': 'abc123',
        }
        self._mock_jobs = {
            'jobs': [
                _job('success', name='lint'),
                _job('failure', name='test',
                     steps=[_step('Run tests', 'failure')]),
            ]
        }

    def _make_get_side_effect(self):
        def side_effect(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.links = {}
            if '/jobs' in url:
                resp.json.return_value = self._mock_jobs
            else:
                resp.json.return_value = self._mock_run_meta
            return resp
        return side_effect

    @patch('collect_ci_results.d1_query')
    @patch('collect_ci_results.get_d1_credentials')
    @patch('collect_ci_results.get_infra_patterns')
    @patch('collect_ci_results.requests.get')
    def test_failed_jobs_list_contains_only_test_failures(
        self, mock_get, mock_infra, mock_creds, mock_d1
    ):
        mock_get.side_effect = self._make_get_side_effect()
        mock_infra.return_value = []
        mock_creds.return_value = ('acct', 'db', 'tok')
        mock_d1.return_value = [{'results': []}]

        with patch('sys.argv', [
            'collect_ci_results.py',
            '--workflow-run-id', '99999',
            '--repo', 'owner/repo',
            '--github-token', 'tok',
        ]):
            with patch('sys.stdout', new_callable=StringIO) as mock_out:
                main()
                output = json.loads(mock_out.getvalue())

        self.assertIn('test', output['failed_jobs'])
        self.assertNotIn('lint', output['failed_jobs'])

    @patch('collect_ci_results.d1_query')
    @patch('collect_ci_results.get_d1_credentials')
    @patch('collect_ci_results.get_infra_patterns')
    @patch('collect_ci_results.requests.get')
    def test_output_contains_all_required_fields(
        self, mock_get, mock_infra, mock_creds, mock_d1
    ):
        mock_get.side_effect = self._make_get_side_effect()
        mock_infra.return_value = []
        mock_creds.return_value = ('acct', 'db', 'tok')
        mock_d1.return_value = [{'results': []}]

        with patch('sys.argv', [
            'collect_ci_results.py',
            '--workflow-run-id', '99999',
            '--repo', 'owner/repo',
            '--github-token', 'tok',
        ]):
            with patch('sys.stdout', new_callable=StringIO) as mock_out:
                main()
                output = json.loads(mock_out.getvalue())

        for key in ('failed_jobs', 'run_attempt', 'workflow_name', 'all_jobs'):
            self.assertIn(key, output)

    @patch('collect_ci_results.d1_query')
    @patch('collect_ci_results.get_d1_credentials')
    @patch('collect_ci_results.get_infra_patterns')
    @patch('collect_ci_results.requests.get')
    def test_dry_run_does_not_call_d1(
        self, mock_get, mock_infra, mock_creds, mock_d1
    ):
        mock_get.side_effect = self._make_get_side_effect()
        mock_infra.return_value = []
        mock_creds.return_value = ('acct', 'db', 'tok')

        with patch('sys.argv', [
            'collect_ci_results.py',
            '--workflow-run-id', '99999',
            '--repo', 'owner/repo',
            '--github-token', 'tok',
            '--dry-run',
        ]):
            with patch('sys.stdout', new_callable=StringIO):
                main()

        mock_d1.assert_not_called()

    @patch('collect_ci_results.d1_query')
    @patch('collect_ci_results.get_d1_credentials')
    @patch('collect_ci_results.get_infra_patterns')
    @patch('collect_ci_results.requests.get')
    def test_d1_insert_called_for_each_job(
        self, mock_get, mock_infra, mock_creds, mock_d1
    ):
        mock_get.side_effect = self._make_get_side_effect()
        mock_infra.return_value = []
        mock_creds.return_value = ('acct', 'db', 'tok')
        mock_d1.return_value = [{'results': []}]

        with patch('sys.argv', [
            'collect_ci_results.py',
            '--workflow-run-id', '99999',
            '--repo', 'owner/repo',
            '--github-token', 'tok',
        ]):
            with patch('sys.stdout', new_callable=StringIO):
                main()

        # 2 jobs + 1 prune DELETE = 3 d1_query calls
        self.assertEqual(mock_d1.call_count, 3)
        # All INSERT calls should target ci_run_history
        insert_calls = [
            c for c in mock_d1.call_args_list
            if 'INSERT INTO ci_run_history' in c[0][3]
        ]
        self.assertEqual(len(insert_calls), 2)

    @patch('collect_ci_results.d1_query')
    @patch('collect_ci_results.get_d1_credentials')
    @patch('collect_ci_results.get_infra_patterns')
    @patch('collect_ci_results.requests.get')
    def test_infrastructure_failure_not_in_failed_jobs(
        self, mock_get, mock_infra, mock_creds, mock_d1
    ):
        # replace the failing job with an infrastructure failure
        self._mock_jobs = {
            'jobs': [
                _job('failure', name='deploy',
                     steps=[_step('Network call ECONNRESET', 'failure')]),
            ]
        }
        mock_get.side_effect = self._make_get_side_effect()
        mock_infra.return_value = ['econnreset']
        mock_creds.return_value = ('acct', 'db', 'tok')
        mock_d1.return_value = [{'results': []}]

        with patch('sys.argv', [
            'collect_ci_results.py',
            '--workflow-run-id', '99999',
            '--repo', 'owner/repo',
            '--github-token', 'tok',
        ]):
            with patch('sys.stdout', new_callable=StringIO) as mock_out:
                main()
                output = json.loads(mock_out.getvalue())

        self.assertEqual(output['failed_jobs'], [])


if __name__ == '__main__':
    unittest.main()
