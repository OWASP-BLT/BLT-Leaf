"""Tests for db_utils.py — Cloudflare D1 REST client."""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import db_utils


class TestGetD1Credentials(unittest.TestCase):
    _KEYS = ('CLOUDFLARE_ACCOUNT_ID', 'CLOUDFLARE_D1_DATABASE_ID', 'CLOUDFLARE_API_TOKEN')

    def setUp(self):
        for key in self._KEYS:
            os.environ.pop(key, None)

    def tearDown(self):
        for key in self._KEYS:
            os.environ.pop(key, None)

    def test_returns_tuple_when_all_present(self):
        os.environ['CLOUDFLARE_ACCOUNT_ID'] = 'acct123'
        os.environ['CLOUDFLARE_D1_DATABASE_ID'] = 'db456'
        os.environ['CLOUDFLARE_API_TOKEN'] = 'tok789'
        self.assertEqual(db_utils.get_d1_credentials(), ('acct123', 'db456', 'tok789'))

    def test_raises_when_one_var_missing(self):
        os.environ['CLOUDFLARE_ACCOUNT_ID'] = 'acct123'
        os.environ['CLOUDFLARE_D1_DATABASE_ID'] = 'db456'
        with self.assertRaises(RuntimeError) as ctx:
            db_utils.get_d1_credentials()
        self.assertIn('CLOUDFLARE_API_TOKEN', str(ctx.exception))

    def test_raises_when_all_vars_missing(self):
        with self.assertRaises(RuntimeError) as ctx:
            db_utils.get_d1_credentials()
        msg = str(ctx.exception)
        self.assertIn('CLOUDFLARE_ACCOUNT_ID', msg)
        self.assertIn('CLOUDFLARE_D1_DATABASE_ID', msg)
        self.assertIn('CLOUDFLARE_API_TOKEN', msg)

    def test_error_message_lists_only_missing_vars(self):
        os.environ['CLOUDFLARE_ACCOUNT_ID'] = 'acct'
        with self.assertRaises(RuntimeError) as ctx:
            db_utils.get_d1_credentials()
        msg = str(ctx.exception)
        self.assertNotIn('CLOUDFLARE_ACCOUNT_ID', msg)
        self.assertIn('CLOUDFLARE_D1_DATABASE_ID', msg)
        self.assertIn('CLOUDFLARE_API_TOKEN', msg)


class TestD1Query(unittest.TestCase):
    def _mock_response(self, json_data, status_code=200):
        mock = MagicMock()
        mock.json.return_value = json_data
        mock.status_code = status_code
        if status_code >= 400:
            from requests.exceptions import HTTPError
            mock.raise_for_status.side_effect = HTTPError(response=mock)
        else:
            mock.raise_for_status = MagicMock()
        return mock

    @patch('db_utils.requests.post')
    def test_success_returns_result_list(self, mock_post):
        payload = {'success': True, 'result': [{'results': [{'id': 1}]}]}
        mock_post.return_value = self._mock_response(payload)
        result = db_utils.d1_query('acct', 'db', 'tok', 'SELECT 1')
        self.assertEqual(result, payload['result'])

    @patch('db_utils.requests.post')
    def test_sends_correct_url_containing_account_and_db(self, mock_post):
        mock_post.return_value = self._mock_response({'success': True, 'result': []})
        db_utils.d1_query('acct123', 'db456', 'mytoken', 'SELECT 1')
        url = mock_post.call_args[0][0]
        self.assertIn('acct123', url)
        self.assertIn('db456', url)

    @patch('db_utils.requests.post')
    def test_sends_bearer_auth_header(self, mock_post):
        mock_post.return_value = self._mock_response({'success': True, 'result': []})
        db_utils.d1_query('a', 'b', 'mytoken', 'SELECT 1')
        headers = mock_post.call_args[1]['headers']
        self.assertEqual(headers['Authorization'], 'Bearer mytoken')

    @patch('db_utils.requests.post')
    def test_sends_sql_and_params_in_body(self, mock_post):
        mock_post.return_value = self._mock_response({'success': True, 'result': []})
        db_utils.d1_query('a', 'b', 'c', 'SELECT * WHERE id = ?', params=[42])
        body = mock_post.call_args[1]['json']
        self.assertEqual(body['sql'], 'SELECT * WHERE id = ?')
        self.assertEqual(body['params'], [42])

    @patch('db_utils.requests.post')
    def test_omits_params_key_when_none(self, mock_post):
        mock_post.return_value = self._mock_response({'success': True, 'result': []})
        db_utils.d1_query('a', 'b', 'c', 'SELECT 1')
        body = mock_post.call_args[1]['json']
        self.assertNotIn('params', body)

    @patch('db_utils.requests.post')
    def test_raises_runtime_error_on_api_failure(self, mock_post):
        payload = {'success': False, 'errors': [{'message': 'bad sql'}]}
        mock_post.return_value = self._mock_response(payload)
        with self.assertRaises(RuntimeError) as ctx:
            db_utils.d1_query('a', 'b', 'c', 'BAD SQL')
        self.assertIn('D1 query failed', str(ctx.exception))

    @patch('db_utils.requests.post')
    def test_raises_http_error_on_4xx(self, mock_post):
        from requests.exceptions import HTTPError
        mock_post.return_value = self._mock_response({'error': 'unauthorized'}, status_code=401)
        with self.assertRaises(HTTPError):
            db_utils.d1_query('a', 'b', 'c', 'SELECT 1')


class TestD1Select(unittest.TestCase):
    @patch('db_utils.d1_query')
    def test_returns_row_dicts_from_results(self, mock_query):
        rows = [{'id': 1, 'name': 'a'}, {'id': 2, 'name': 'b'}]
        mock_query.return_value = [{'results': rows}]
        self.assertEqual(db_utils.d1_select('a', 'b', 'c', 'SELECT *'), rows)

    @patch('db_utils.d1_query')
    def test_returns_empty_list_when_result_is_empty(self, mock_query):
        mock_query.return_value = []
        self.assertEqual(db_utils.d1_select('a', 'b', 'c', 'SELECT *'), [])

    @patch('db_utils.d1_query')
    def test_returns_empty_list_when_results_key_missing(self, mock_query):
        mock_query.return_value = [{}]
        self.assertEqual(db_utils.d1_select('a', 'b', 'c', 'SELECT *'), [])

    @patch('db_utils.d1_query')
    def test_passes_params_through_to_d1_query(self, mock_query):
        mock_query.return_value = [{'results': []}]
        db_utils.d1_select('a', 'b', 'c', 'SELECT * WHERE id = ?', params=[99])
        mock_query.assert_called_once_with('a', 'b', 'c', 'SELECT * WHERE id = ?', [99])


class TestGetInfraPatterns(unittest.TestCase):
    @patch('db_utils.d1_select')
    def test_returns_lowercase_patterns(self, mock_select):
        mock_select.return_value = [
            {'pattern': 'ECONNRESET'},
            {'pattern': 'Timed_Out'},
            {'pattern': 'network error'},
        ]
        self.assertEqual(
            db_utils.get_infra_patterns('a', 'b', 'c'),
            ['econnreset', 'timed_out', 'network error'],
        )

    @patch('db_utils.d1_select')
    def test_returns_empty_list_when_no_rows(self, mock_select):
        mock_select.return_value = []
        self.assertEqual(db_utils.get_infra_patterns('a', 'b', 'c'), [])

    @patch('db_utils.d1_select')
    def test_queries_correct_table(self, mock_select):
        mock_select.return_value = []
        db_utils.get_infra_patterns('a', 'b', 'c')
        sql = mock_select.call_args[0][3]
        self.assertIn('known_infrastructure_issues', sql)


class TestLoadConfig(unittest.TestCase):
    def setUp(self):
        db_utils._config_cache = None

    def tearDown(self):
        db_utils._config_cache = None

    def test_returns_dict_with_expected_top_level_keys(self):
        config = db_utils.load_config()
        for key in ('thresholds', 'severity', 'github', 'labels'):
            self.assertIn(key, config)

    def test_thresholds_has_all_required_fields(self):
        t = db_utils.load_config()['thresholds']
        for key in ('window_size', 'min_runs', 'flaky_min_rate',
                    'flaky_max_rate', 'consecutive_failures_deterministic'):
            self.assertIn(key, t)

    def test_second_call_returns_same_cached_object(self):
        first = db_utils.load_config()
        second = db_utils.load_config()
        self.assertIs(first, second)


if __name__ == '__main__':
    unittest.main()
