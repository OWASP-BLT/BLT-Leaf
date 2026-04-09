"""Tests for retry_failures.py — trigger_rerun, mark_flake_confirmed, main()."""

import json
import os
import sys
import tempfile
import unittest
from io import StringIO
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import retry_failures
from retry_failures import trigger_rerun, fetch_job_conclusions, mark_flake_confirmed


def _write_collect_output(path, failed_jobs, run_attempt=1):
    data = {'failed_jobs': failed_jobs, 'run_attempt': run_attempt}
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh)


# ---------------------------------------------------------------------------
# trigger_rerun
# ---------------------------------------------------------------------------
class TestTriggerRerun(unittest.TestCase):
    @patch('retry_failures.requests.post')
    def test_returns_false_on_403(self, mock_post):
        resp = MagicMock()
        resp.status_code = 403
        mock_post.return_value = resp
        self.assertFalse(trigger_rerun('owner', 'repo', 12345, 'token'))

    @patch('retry_failures.requests.post')
    def test_returns_true_on_success(self, mock_post):
        resp = MagicMock()
        resp.status_code = 201
        resp.raise_for_status = MagicMock()
        mock_post.return_value = resp
        self.assertTrue(trigger_rerun('owner', 'repo', 12345, 'token'))

    @patch('retry_failures.requests.post')
    def test_calls_correct_github_endpoint(self, mock_post):
        resp = MagicMock()
        resp.status_code = 201
        resp.raise_for_status = MagicMock()
        mock_post.return_value = resp
        trigger_rerun('myowner', 'myrepo', 99, 'tok')
        url = mock_post.call_args[0][0]
        self.assertIn('myowner/myrepo', url)
        self.assertIn('rerun-failed-jobs', url)


# ---------------------------------------------------------------------------
# fetch_job_conclusions
# ---------------------------------------------------------------------------
class TestFetchJobConclusions(unittest.TestCase):
    @patch('retry_failures.requests.get')
    def test_returns_name_to_conclusion_mapping(self, mock_get):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.links = {}
        resp.json.return_value = {
            'jobs': [
                {'name': 'lint', 'conclusion': 'success'},
                {'name': 'test', 'conclusion': 'failure'},
            ]
        }
        mock_get.return_value = resp
        result = fetch_job_conclusions('owner', 'repo', 12345, 'tok')
        self.assertEqual(result, {'lint': 'success', 'test': 'failure'})

    @patch('retry_failures.requests.get')
    def test_follows_pagination_links(self, mock_get):
        page1 = MagicMock()
        page1.raise_for_status = MagicMock()
        page1.links = {'next': {'url': 'https://api.github.com/page2'}}
        page1.json.return_value = {'jobs': [{'name': 'job1', 'conclusion': 'success'}]}

        page2 = MagicMock()
        page2.raise_for_status = MagicMock()
        page2.links = {}
        page2.json.return_value = {'jobs': [{'name': 'job2', 'conclusion': 'failure'}]}

        mock_get.side_effect = [page1, page2]
        result = fetch_job_conclusions('owner', 'repo', 12345, 'tok')
        self.assertIn('job1', result)
        self.assertIn('job2', result)
        self.assertEqual(mock_get.call_count, 2)

    @patch('retry_failures.requests.get')
    def test_returns_none_for_in_progress_job(self, mock_get):
        # A job with conclusion=None means it is still in-progress;
        # the code returns None directly (not 'unknown') in that case.
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.links = {}
        resp.json.return_value = {'jobs': [{'name': 'job', 'conclusion': None}]}
        mock_get.return_value = resp
        result = fetch_job_conclusions('owner', 'repo', 12345, 'tok')
        self.assertIsNone(result['job'])


# ---------------------------------------------------------------------------
# mark_flake_confirmed
# ---------------------------------------------------------------------------
class TestMarkFlakeConfirmed(unittest.TestCase):
    @patch('retry_failures.d1_query')
    def test_calls_d1_query_once(self, mock_d1):
        mock_d1.return_value = [{'results': []}]
        mark_flake_confirmed('acct', 'db', 'tok', 99999, 'test-job', 'owner/repo', 2)
        mock_d1.assert_called_once()

    @patch('retry_failures.d1_query')
    def test_sql_targets_ci_run_history(self, mock_d1):
        mock_d1.return_value = [{'results': []}]
        mark_flake_confirmed('acct', 'db', 'tok', 99999, 'test-job', 'owner/repo', 2)
        sql = mock_d1.call_args[0][3]
        self.assertIn('INSERT INTO ci_run_history', sql)

    @patch('retry_failures.d1_query')
    def test_params_include_run_id_attempt_job_and_repo(self, mock_d1):
        mock_d1.return_value = [{'results': []}]
        mark_flake_confirmed('acct', 'db', 'tok', 99999, 'test-job', 'owner/repo', 2)
        params = mock_d1.call_args[0][4]
        self.assertIn(99999, params)      # workflow_run_id
        self.assertIn(2, params)          # new_attempt
        self.assertIn('test-job', params)
        self.assertIn('owner/repo', params)

    @patch('retry_failures.d1_query')
    def test_inserts_flake_confirmed_conclusion(self, mock_d1):
        mock_d1.return_value = [{'results': []}]
        mark_flake_confirmed('acct', 'db', 'tok', 99999, 'test-job', 'owner/repo', 2)
        sql = mock_d1.call_args[0][3]
        self.assertIn('flake_confirmed', sql)


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------
class TestRetryMain(unittest.TestCase):
    @patch('retry_failures.get_d1_credentials')
    def test_skips_when_already_retried_run_attempt_gt_1(self, mock_creds):
        with tempfile.TemporaryDirectory() as tmpdir:
            collect_file = os.path.join(tmpdir, 'collect.json')
            _write_collect_output(collect_file, ['test'], run_attempt=2)

            with patch('sys.argv', [
                'retry_failures.py',
                '--workflow-run-id', '12345',
                '--repo', 'owner/repo',
                '--collect-output', collect_file,
            ]):
                with patch('sys.stdout', new_callable=StringIO) as mock_out:
                    retry_failures.main()
                    output = json.loads(mock_out.getvalue())

        self.assertEqual(output['test'], 'skipped_already_retried')
        mock_creds.assert_not_called()

    def test_empty_failed_jobs_outputs_empty_dict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            collect_file = os.path.join(tmpdir, 'collect.json')
            _write_collect_output(collect_file, [], run_attempt=1)

            with patch('sys.argv', [
                'retry_failures.py',
                '--workflow-run-id', '12345',
                '--repo', 'owner/repo',
                '--collect-output', collect_file,
            ]):
                with patch('sys.stdout', new_callable=StringIO) as mock_out:
                    retry_failures.main()
                    output = json.loads(mock_out.getvalue())

        self.assertEqual(output, {})

    @patch('retry_failures.get_d1_credentials')
    @patch('retry_failures.trigger_rerun')
    def test_rerun_not_permitted_when_trigger_returns_false(
        self, mock_trigger, mock_creds
    ):
        mock_creds.return_value = ('acct', 'db', 'tok')
        mock_trigger.return_value = False

        with tempfile.TemporaryDirectory() as tmpdir:
            collect_file = os.path.join(tmpdir, 'collect.json')
            _write_collect_output(collect_file, ['test'], run_attempt=1)

            with patch('sys.argv', [
                'retry_failures.py',
                '--workflow-run-id', '12345',
                '--repo', 'owner/repo',
                '--collect-output', collect_file,
            ]):
                with patch('sys.stdout', new_callable=StringIO) as mock_out:
                    retry_failures.main()
                    output = json.loads(mock_out.getvalue())

        self.assertEqual(output['test'], 'rerun_not_permitted')

    @patch('retry_failures.get_d1_credentials')
    @patch('retry_failures.trigger_rerun')
    @patch('retry_failures.poll_run_completion')
    def test_poll_timeout_result_when_poll_returns_none(
        self, mock_poll, mock_trigger, mock_creds
    ):
        mock_creds.return_value = ('acct', 'db', 'tok')
        mock_trigger.return_value = True
        mock_poll.return_value = (None, None)

        with tempfile.TemporaryDirectory() as tmpdir:
            collect_file = os.path.join(tmpdir, 'collect.json')
            _write_collect_output(collect_file, ['test'], run_attempt=1)

            with patch('sys.argv', [
                'retry_failures.py',
                '--workflow-run-id', '12345',
                '--repo', 'owner/repo',
                '--collect-output', collect_file,
            ]):
                with patch('sys.stdout', new_callable=StringIO) as mock_out:
                    retry_failures.main()
                    output = json.loads(mock_out.getvalue())

        self.assertEqual(output['test'], 'poll_timeout')

    @patch('retry_failures.mark_flake_confirmed')
    @patch('retry_failures.fetch_job_conclusions')
    @patch('retry_failures.poll_run_completion')
    @patch('retry_failures.trigger_rerun')
    @patch('retry_failures.get_d1_credentials')
    def test_confirmed_flake_when_job_passes_on_retry(
        self, mock_creds, mock_trigger, mock_poll, mock_fetch, mock_mark
    ):
        mock_creds.return_value = ('acct', 'db', 'tok')
        mock_trigger.return_value = True
        mock_poll.return_value = ('success', 2)
        mock_fetch.return_value = {'test': 'success'}

        with tempfile.TemporaryDirectory() as tmpdir:
            collect_file = os.path.join(tmpdir, 'collect.json')
            _write_collect_output(collect_file, ['test'], run_attempt=1)

            with patch('sys.argv', [
                'retry_failures.py',
                '--workflow-run-id', '12345',
                '--repo', 'owner/repo',
                '--collect-output', collect_file,
            ]):
                with patch('sys.stdout', new_callable=StringIO) as mock_out:
                    retry_failures.main()
                    output = json.loads(mock_out.getvalue())

        self.assertEqual(output['test'], 'confirmed_flake')
        mock_mark.assert_called_once_with('acct', 'db', 'tok', 12345, 'test', 'owner/repo', 2)

    @patch('retry_failures.d1_query')
    @patch('retry_failures.fetch_job_conclusions')
    @patch('retry_failures.poll_run_completion')
    @patch('retry_failures.trigger_rerun')
    @patch('retry_failures.get_d1_credentials')
    def test_real_failure_when_job_fails_on_retry(
        self, mock_creds, mock_trigger, mock_poll, mock_fetch, mock_d1
    ):
        mock_creds.return_value = ('acct', 'db', 'tok')
        mock_trigger.return_value = True
        mock_poll.return_value = ('failure', 2)
        mock_fetch.return_value = {'test': 'failure'}

        with tempfile.TemporaryDirectory() as tmpdir:
            collect_file = os.path.join(tmpdir, 'collect.json')
            _write_collect_output(collect_file, ['test'], run_attempt=1)

            with patch('sys.argv', [
                'retry_failures.py',
                '--workflow-run-id', '12345',
                '--repo', 'owner/repo',
                '--collect-output', collect_file,
            ]):
                with patch('sys.stdout', new_callable=StringIO) as mock_out:
                    retry_failures.main()
                    output = json.loads(mock_out.getvalue())

        self.assertEqual(output['test'], 'real_failure')
        mock_d1.assert_not_called()

    @patch('retry_failures.mark_flake_confirmed')
    @patch('retry_failures.fetch_job_conclusions')
    @patch('retry_failures.poll_run_completion')
    @patch('retry_failures.trigger_rerun')
    @patch('retry_failures.get_d1_credentials')
    def test_multiple_jobs_classified_independently(
        self, mock_creds, mock_trigger, mock_poll, mock_fetch, mock_mark
    ):
        mock_creds.return_value = ('acct', 'db', 'tok')
        mock_trigger.return_value = True
        mock_poll.return_value = ('success', 2)
        mock_fetch.return_value = {'job-a': 'success', 'job-b': 'failure'}

        with tempfile.TemporaryDirectory() as tmpdir:
            collect_file = os.path.join(tmpdir, 'collect.json')
            _write_collect_output(collect_file, ['job-a', 'job-b'], run_attempt=1)

            with patch('sys.argv', [
                'retry_failures.py',
                '--workflow-run-id', '12345',
                '--repo', 'owner/repo',
                '--collect-output', collect_file,
            ]):
                with patch('sys.stdout', new_callable=StringIO) as mock_out:
                    retry_failures.main()
                    output = json.loads(mock_out.getvalue())

        self.assertEqual(output['job-a'], 'confirmed_flake')
        self.assertEqual(output['job-b'], 'real_failure')


if __name__ == '__main__':
    unittest.main()
