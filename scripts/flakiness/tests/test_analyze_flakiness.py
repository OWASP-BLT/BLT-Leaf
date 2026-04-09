"""Tests for analyze_flakiness.py — pure functions and main() integration."""

import json
import os
import sys
import unittest
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import db_utils
from analyze_flakiness import _get_severity, analyze_check, main


# ---------------------------------------------------------------------------
# Minimal config matching flakiness_config.yml defaults
# ---------------------------------------------------------------------------
_CONFIG = {
    'thresholds': {
        'window_size': 20,
        'min_runs': 5,
        'flaky_min_rate': 0.10,
        'flaky_max_rate': 0.60,
        'consecutive_failures_deterministic': 3,
    },
    'severity': {
        'low':    [0.10, 0.20],
        'medium': [0.20, 0.40],
    },
}


def _row(status, category):
    return {'status': status, 'conclusion_category': category}


def _passes(n):
    return [_row('pass', 'pass')] * n


def _failures(n, category='test_failure'):
    return [_row('fail', category)] * n


# ---------------------------------------------------------------------------
# _get_severity
# ---------------------------------------------------------------------------
class TestGetSeverity(unittest.TestCase):
    def test_below_low_threshold_returns_stable(self):
        self.assertEqual(_get_severity(0.05, _CONFIG), 'stable')

    def test_exactly_at_low_min_returns_low(self):
        self.assertEqual(_get_severity(0.10, _CONFIG), 'low')

    def test_in_low_band_returns_low(self):
        self.assertEqual(_get_severity(0.15, _CONFIG), 'low')

    def test_at_low_upper_bound_enters_medium(self):
        # 0.20 >= medium low [0.20, 0.40] → medium
        self.assertEqual(_get_severity(0.20, _CONFIG), 'medium')

    def test_in_medium_band_returns_medium(self):
        self.assertEqual(_get_severity(0.30, _CONFIG), 'medium')

    def test_above_medium_upper_bound_returns_high(self):
        self.assertEqual(_get_severity(0.45, _CONFIG), 'high')

    def test_zero_returns_stable(self):
        self.assertEqual(_get_severity(0.0, _CONFIG), 'stable')

    def test_one_returns_high(self):
        self.assertEqual(_get_severity(1.0, _CONFIG), 'high')


# ---------------------------------------------------------------------------
# analyze_check
# ---------------------------------------------------------------------------
class TestAnalyzeCheck(unittest.TestCase):
    def test_returns_none_when_insufficient_runs(self):
        # 4 rows < min_runs=5
        self.assertIsNone(analyze_check(_passes(3) + _failures(1), _CONFIG))

    def test_returns_none_when_all_rows_are_infrastructure(self):
        rows = _failures(5, category='infrastructure')
        self.assertIsNone(analyze_check(rows, _CONFIG))

    def test_stable_with_zero_failures(self):
        result = analyze_check(_passes(8), _CONFIG)
        self.assertIsNotNone(result)
        self.assertEqual(result['classification'], 'stable')
        self.assertEqual(result['flakiness_score'], 0.0)

    def test_flaky_with_failure_rate_in_range(self):
        # 8 passes + 2 failures = 20% → flaky (in [0.10, 0.60])
        result = analyze_check(_passes(8) + _failures(2), _CONFIG)
        self.assertIsNotNone(result)
        self.assertEqual(result['classification'], 'flaky')
        self.assertAlmostEqual(result['flakiness_score'], 0.2)

    def test_flaky_severity_assigned(self):
        rows = _passes(8) + _failures(2)
        result = analyze_check(rows, _CONFIG)
        self.assertIn(result['severity'], ('low', 'medium', 'high'))

    def test_deterministic_by_consecutive_failures(self):
        # 5 passes then exactly 3 consecutive test_failures → deterministic
        result = analyze_check(_passes(5) + _failures(3), _CONFIG)
        self.assertIsNotNone(result)
        self.assertEqual(result['classification'], 'deterministic')
        self.assertEqual(result['consecutive_failures'], 3)

    def test_deterministic_by_high_failure_rate(self):
        # 2 passes + 8 failures = 80% > flaky_max=0.60 → deterministic
        result = analyze_check(_passes(2) + _failures(8), _CONFIG)
        self.assertIsNotNone(result)
        self.assertEqual(result['classification'], 'deterministic')

    def test_infrastructure_rows_excluded_from_window(self):
        # 3 infra rows + 5 pass rows → only 5 effective non-infra rows
        rows = _failures(3, category='infrastructure') + _passes(5)
        result = analyze_check(rows, _CONFIG)
        self.assertIsNotNone(result)
        self.assertEqual(result['total_runs'], 5)
        self.assertEqual(result['classification'], 'stable')

    def test_flake_confirmed_rows_counted_in_flaky_failures(self):
        rows = (
            _passes(7)
            + [_row('pass', 'flake_confirmed')] * 2
            + _failures(1)
        )
        result = analyze_check(rows, _CONFIG)
        self.assertIsNotNone(result)
        self.assertEqual(result['flaky_failures'], 2)

    def test_window_size_limits_history_analyzed(self):
        # 25 rows: first 5 failures, then 20 passes.
        # With window=20, only the last 20 (all passes) are considered → stable.
        rows = _failures(5) + _passes(20)
        result = analyze_check(rows, _CONFIG)
        self.assertIsNotNone(result)
        self.assertEqual(result['total_runs'], 20)
        self.assertEqual(result['classification'], 'stable')

    def test_consecutive_count_ignores_infrastructure_failures(self):
        # 5 passes, 2 infra fails, 2 test_failures at the end
        # Infrastructure rows are filtered; consecutive test_failures = 2 (< 3 → not deterministic)
        rows = _passes(5) + _failures(2, 'infrastructure') + _failures(2, 'test_failure')
        result = analyze_check(rows, _CONFIG)
        self.assertIsNotNone(result)
        self.assertEqual(result['consecutive_failures'], 2)
        # total non-infra = 7, failures = 2, rate = 0.286 → flaky
        self.assertEqual(result['classification'], 'flaky')

    def test_result_contains_all_required_fields(self):
        rows = _passes(8) + _failures(2)
        result = analyze_check(rows, _CONFIG)
        for field in ('classification', 'flakiness_score', 'severity',
                      'total_runs', 'failure_count', 'flaky_failures',
                      'consecutive_failures'):
            self.assertIn(field, result)

    def test_deterministic_score_is_zero(self):
        rows = _passes(5) + _failures(4)
        result = analyze_check(rows, _CONFIG)
        self.assertEqual(result['classification'], 'deterministic')
        self.assertEqual(result['flakiness_score'], 0.0)

    def test_stable_score_is_zero(self):
        rows = _passes(10)
        result = analyze_check(rows, _CONFIG)
        self.assertEqual(result['flakiness_score'], 0.0)

    def test_exactly_at_flaky_min_rate_is_flaky(self):
        # 9 passes + 1 failure = 10% = flaky_min_rate exact boundary → flaky
        rows = _passes(9) + _failures(1)
        result = analyze_check(rows, _CONFIG)
        self.assertIsNotNone(result)
        self.assertEqual(result['classification'], 'flaky')


# ---------------------------------------------------------------------------
# main() integration
# ---------------------------------------------------------------------------
class TestAnalyzeMain(unittest.TestCase):
    def _history_rows(self):
        """10-row history: 6 passes, 2 failures, 2 passes → 20% → flaky (no trailing streak)."""
        return _passes(6) + _failures(2) + _passes(2)

    @patch('analyze_flakiness.d1_query')
    @patch('analyze_flakiness.d1_select')
    @patch('analyze_flakiness.get_d1_credentials')
    def test_main_outputs_valid_json_with_expected_keys(
        self, mock_creds, mock_select, mock_query
    ):
        mock_creds.return_value = ('acct', 'db', 'tok')
        combo = {'check_name': 'lint', 'job_name': 'lint', 'workflow_name': 'CI'}
        mock_select.side_effect = [[combo], self._history_rows()]
        mock_query.return_value = [{'results': []}]

        with patch('sys.argv', ['analyze_flakiness.py', '--repo', 'owner/repo']):
            with patch('sys.stdout', new_callable=StringIO) as mock_out:
                main()
                output = json.loads(mock_out.getvalue())

        self.assertIn('flaky', output)
        self.assertIn('deterministic', output)
        self.assertIn('stable', output)

    @patch('analyze_flakiness.d1_query')
    @patch('analyze_flakiness.d1_select')
    @patch('analyze_flakiness.get_d1_credentials')
    def test_main_classifies_flaky_check_correctly(
        self, mock_creds, mock_select, mock_query
    ):
        mock_creds.return_value = ('acct', 'db', 'tok')
        combo = {'check_name': 'lint', 'job_name': 'lint', 'workflow_name': 'CI'}
        mock_select.side_effect = [[combo], self._history_rows()]
        mock_query.return_value = [{'results': []}]

        with patch('sys.argv', ['analyze_flakiness.py', '--repo', 'owner/repo']):
            with patch('sys.stdout', new_callable=StringIO) as mock_out:
                main()
                output = json.loads(mock_out.getvalue())

        self.assertEqual(len(output['flaky']), 1)
        self.assertEqual(output['flaky'][0]['check_name'], 'lint')

    @patch('analyze_flakiness.d1_query')
    @patch('analyze_flakiness.d1_select')
    @patch('analyze_flakiness.get_d1_credentials')
    def test_main_skips_checks_with_insufficient_history(
        self, mock_creds, mock_select, mock_query
    ):
        mock_creds.return_value = ('acct', 'db', 'tok')
        combo = {'check_name': 'new-job', 'job_name': 'new-job', 'workflow_name': 'CI'}
        # Only 3 rows — below min_runs=5
        mock_select.side_effect = [[combo], _passes(3)]
        mock_query.return_value = [{'results': []}]

        with patch('sys.argv', ['analyze_flakiness.py', '--repo', 'owner/repo']):
            with patch('sys.stdout', new_callable=StringIO) as mock_out:
                main()
                output = json.loads(mock_out.getvalue())

        # Should not appear in any category
        total = (len(output['flaky']) + len(output['deterministic'])
                 + len(output['stable']))
        self.assertEqual(total, 0)

    @patch('analyze_flakiness.d1_query')
    @patch('analyze_flakiness.d1_select')
    @patch('analyze_flakiness.get_d1_credentials')
    def test_main_upserts_score_for_each_classified_check(
        self, mock_creds, mock_select, mock_query
    ):
        mock_creds.return_value = ('acct', 'db', 'tok')
        combo = {'check_name': 'lint', 'job_name': 'lint', 'workflow_name': 'CI'}
        mock_select.side_effect = [[combo], self._history_rows()]
        mock_query.return_value = [{'results': []}]

        with patch('sys.argv', ['analyze_flakiness.py', '--repo', 'owner/repo']):
            with patch('sys.stdout', new_callable=StringIO):
                main()

        # d1_query should be called once to upsert the score
        mock_query.assert_called_once()
        sql = mock_query.call_args[0][3]
        self.assertIn('INSERT INTO flakiness_scores', sql)
        self.assertIn('ON CONFLICT', sql)


if __name__ == '__main__':
    unittest.main()
