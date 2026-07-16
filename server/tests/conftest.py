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

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app as app_module  # noqa: E402
import db  # noqa: E402


# A deterministic bag-of-words embedder so the semantic paths are exercised
# without loading torch / downloading a model. Each idea/query maps to a
# normalized count vector over a fixed vocabulary; cosine = dot product.
_VOCAB = [
    "firewall", "tunnel", "ssh", "port", "reach", "service", "vm",
    "tree", "model", "arithmetic", "feature", "engineering",
    "multigrid", "coarse", "space", "null", "algebraic",
    "agent", "tool", "recover", "retry", "fail",
    "llm", "evaluate", "answer", "correct", "grade",
]


class FakeEmbedder:
    dim = len(_VOCAB)

    def encode(self, texts):
        out = []
        for text in texts:
            tokens = "".join(c if c.isalnum() else " " for c in text.lower()).split()
            vec = np.zeros(len(_VOCAB), dtype=np.float32)
            for i, word in enumerate(_VOCAB):
                vec[i] = float(tokens.count(word))
            norm = float(np.linalg.norm(vec))
            if norm > 0:
                vec /= norm
            out.append(vec)
        return np.stack(out).astype(np.float32)


# Inject the fake so the real model is never constructed during tests.
app_module.rag.set_embedder(FakeEmbedder())

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
    app_module.rag._vecs.clear()  # drop the in-memory index alongside the rows
    app_module.rag.enabled = True
    yield


@pytest.fixture
def client():
    return TestClient(app_module.app)


@pytest.fixture
def auth():
    return dict(_AUTH)
