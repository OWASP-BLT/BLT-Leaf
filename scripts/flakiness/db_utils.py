"""Shared SQLite helpers for the flakiness detection pipeline."""

import os
import sqlite3

import yaml

_SCRIPTS_DIR = os.path.dirname(__file__)
_REPO_ROOT = os.path.join(_SCRIPTS_DIR, '..', '..')

DB_PATH = os.path.normpath(os.path.join(_REPO_ROOT, 'data', 'flakiness_history.db'))
CONFIG_PATH = os.path.normpath(os.path.join(_SCRIPTS_DIR, 'flakiness_config.yml'))

_config_cache = None


def load_config():
    """Load and cache flakiness_config.yml."""
    global _config_cache
    if _config_cache is None:
        with open(CONFIG_PATH, encoding='utf-8') as f:
            _config_cache = yaml.safe_load(f)
    return _config_cache


def get_db_connection(path=None):
    """Open (or create) the SQLite database, run init_schema, and return the connection."""
    db_path = path or DB_PATH
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    init_schema(conn)
    return conn


def init_schema(conn):
    """Create all flakiness tables if they don't exist and seed infra patterns."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ci_run_history (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            check_name          TEXT    NOT NULL,
            job_name            TEXT    NOT NULL,
            workflow_name       TEXT    NOT NULL,
            workflow_run_id     INTEGER NOT NULL,
            run_attempt         INTEGER NOT NULL DEFAULT 1,
            status              TEXT    NOT NULL,
            conclusion_category TEXT    NOT NULL,
            commit_sha          TEXT    NOT NULL,
            pr_number           INTEGER,
            repo                TEXT    NOT NULL,
            timestamp           TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_ci_run_history_lookup
            ON ci_run_history(check_name, job_name, repo, timestamp);

        CREATE TABLE IF NOT EXISTS flakiness_scores (
            check_name            TEXT    NOT NULL,
            job_name              TEXT    NOT NULL,
            workflow_name         TEXT    NOT NULL,
            flakiness_score       REAL    NOT NULL DEFAULT 0.0,
            severity              TEXT    NOT NULL DEFAULT 'stable',
            classification        TEXT    NOT NULL DEFAULT 'stable',
            total_runs            INTEGER NOT NULL DEFAULT 0,
            failure_count         INTEGER NOT NULL DEFAULT 0,
            flaky_failures        INTEGER NOT NULL DEFAULT 0,
            consecutive_failures  INTEGER NOT NULL DEFAULT 0,
            last_updated          TEXT    NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (check_name, job_name)
        );

        CREATE TABLE IF NOT EXISTS known_infrastructure_issues (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern     TEXT NOT NULL UNIQUE,
            category    TEXT NOT NULL DEFAULT 'infrastructure',
            description TEXT,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)

    conn.executemany(
        "INSERT OR IGNORE INTO known_infrastructure_issues (pattern, category, description) VALUES (?, ?, ?)",
        [
            ('ECONNRESET',             'infrastructure', 'TCP connection reset — transient network issue'),
            ('timed_out',              'infrastructure', 'GitHub Actions step conclusion: timed_out'),
            ('timeout',                'infrastructure', 'Generic timeout — network or infrastructure issue'),
            ('rate limit',             'infrastructure', 'API or package registry rate limit hit'),
            ('ETIMEDOUT',              'infrastructure', 'TCP connection timed out'),
            ('fetch failed',           'infrastructure', 'Network fetch failure — transient'),
            ('network error',          'infrastructure', 'Generic network error'),
            ('Could not resolve host', 'infrastructure', 'DNS resolution failure'),
        ]
    )
    conn.commit()


def get_infra_patterns(conn):
    """Return a list of lowercase infrastructure pattern strings."""
    rows = conn.execute("SELECT pattern FROM known_infrastructure_issues").fetchall()
    return [row['pattern'].lower() for row in rows]
