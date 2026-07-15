"""Test fixtures: point the app at a throwaway SQLite file and a known token.

Env must be set BEFORE importing app/config (config loads at import time).
"""
import os
import sys
import tempfile

# Make server modules importable as top-level (app, db, ids, export, ...).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ.setdefault("IDEAL_TOKEN", "test-token")
os.environ.setdefault("IDEAL_PROTECT_READS", "true")
_fd, _db_path = tempfile.mkstemp(suffix=".sqlite")
os.close(_fd)
os.environ["IDEAL_DB_PATH"] = _db_path

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app as app_module  # noqa: E402
import db  # noqa: E402

_AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture(scope="session", autouse=True)
def _schema():
    db.init_schema()
    yield


@pytest.fixture(autouse=True)
def _clean_tables():
    conn = db.connect()
    try:
        conn.execute("DELETE FROM links")
        conn.execute("DELETE FROM ideas")
    finally:
        conn.close()
    yield


@pytest.fixture
def client():
    return TestClient(app_module.app)


@pytest.fixture
def auth():
    return dict(_AUTH)
