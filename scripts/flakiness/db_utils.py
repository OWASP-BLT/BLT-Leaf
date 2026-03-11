"""Cloudflare D1 REST API client for the flakiness detection pipeline."""

import os

import requests
import yaml

_SCRIPTS_DIR = os.path.dirname(__file__)
CONFIG_PATH = os.path.normpath(os.path.join(_SCRIPTS_DIR, 'flakiness_config.yml'))

_config_cache = None


def load_config():
    """Load and cache flakiness_config.yml."""
    global _config_cache
    if _config_cache is None:
        with open(CONFIG_PATH, encoding='utf-8') as f:
            _config_cache = yaml.safe_load(f)
    return _config_cache


def get_d1_credentials():
    """
    Read D1 credentials from environment variables.
    Raises RuntimeError with a clear message if any are missing.
    """
    account_id = os.environ.get('CLOUDFLARE_ACCOUNT_ID')
    db_id      = os.environ.get('CLOUDFLARE_D1_DATABASE_ID')
    token      = os.environ.get('CLOUDFLARE_API_TOKEN')
    missing = [k for k, v in {
        'CLOUDFLARE_ACCOUNT_ID':    account_id,
        'CLOUDFLARE_D1_DATABASE_ID': db_id,
        'CLOUDFLARE_API_TOKEN':     token,
    }.items() if not v]
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}"
        )
    return account_id, db_id, token


def d1_query(account_id, db_id, token, sql, params=None):
    """
    Execute a SQL statement against Cloudflare D1 via the REST API.
    Returns the raw result list from the API response.
    Raises RuntimeError if the API reports failure.
    """
    url = (
        f'https://api.cloudflare.com/client/v4/accounts/{account_id}'
        f'/d1/database/{db_id}/query'
    )
    body = {'sql': sql}
    if params is not None:
        body['params'] = params
    resp = requests.post(
        url,
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        },
        json=body,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get('success'):
        raise RuntimeError(f'D1 query failed: {data.get("errors")}')
    return data.get('result', [])


def d1_select(account_id, db_id, token, sql, params=None):
    """
    Execute a SELECT and return a list of row dicts.
    Convenience wrapper around d1_query().
    """
    result = d1_query(account_id, db_id, token, sql, params)
    if not result:
        return []
    return result[0].get('results', [])


def get_infra_patterns(account_id, db_id, token):
    """Return a list of lowercase infrastructure pattern strings from D1."""
    rows = d1_select(
        account_id, db_id, token,
        'SELECT pattern FROM known_infrastructure_issues',
    )
    return [row['pattern'].lower() for row in rows]
