"""Shared fixtures: a deterministic fake ``Embeddings`` and a small sample export.

The fake maps a fixed vocabulary to L2-normalized term-frequency vectors, so cosine behaves
realistically — a query sharing words with an idea ranks high — with no torch and no network.
"""
import re

import pytest
from langchain_core.embeddings import Embeddings

from rag.store import to_documents

VOCAB = ["firewall", "port", "ssh", "tunnel", "feature", "engineering",
         "tree", "arithmetic", "solver", "multigrid", "embedding", "query"]
_IDX = {w: i for i, w in enumerate(VOCAB)}


class FakeEmbeddings(Embeddings):
    """Bag-of-words TF vectors over a fixed vocab. Counts embed_documents() calls."""

    def __init__(self):
        self.calls = 0

    def _vec(self, text):
        v = [0.0] * len(VOCAB)
        for tok in re.findall(r"[a-z]+", text.lower()):
            if tok in _IDX:
                v[_IDX[tok]] += 1.0
        n = sum(x * x for x in v) ** 0.5
        return [x / n for x in v] if n else v

    def embed_documents(self, texts):
        self.calls += 1
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


@pytest.fixture
def embeddings():
    return FakeEmbeddings()


@pytest.fixture
def sample_export():
    """Two firewall/infra ideas linked (connected), an FE idea, a solver idea.

    ssh-tunnel's text has no query words 'firewall'/'port' — it is only reachable via the edge.
    firewall-two-layers links to ssh-tunnel and to a dangling 'ghost' id that must be dropped.
    """
    return {
        "ideas": [
            {"id": "firewall-two-layers", "title": "Two firewall layers",
             "body": "A port must be open in host firewall and cloud firewall.",
             "tags": ["firewall"],
             "meta": {"source": "arXiv:1234.5678", "title": "Layered Nets", "year": 2023},
             "links_out": [
                 {"target_id": "ssh-tunnel", "type": "connected",
                  "note": "alternative to opening the port"},
                 {"target_id": "ghost", "type": "connected", "note": "dangling"},
             ]},
            {"id": "ssh-tunnel", "title": "SSH tunnel reaches a service",
             "body": "An ssh tunnel forwards a remote service without opening anything.",
             "tags": ["ssh"], "links_out": []},
            {"id": "arithmetic-features", "title": "Give trees arithmetic features",
             "body": "Tree models lack an arithmetic inductive bias so add feature engineering.",
             "tags": ["feature"], "links_out": []},
            {"id": "learn-multigrid", "title": "Learn a multigrid solver parameter",
             "body": "A solver tunes multigrid threshold.",
             "tags": ["solver"], "links_out": []},
        ]
    }


@pytest.fixture
def documents(sample_export):
    return to_documents(sample_export)
