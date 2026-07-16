"""POST /search — the optional server-side GraphRAG. Uses the FakeEmbedder
injected in conftest, so no torch/model is needed.

Vocabulary the fake understands (see conftest): a "firewall/port/service" cluster
and a disjoint "coarse/algebraic/multigrid" cluster, so a query in one cluster
scores ~0 on ideas from the other.
"""
import numpy as np

import app as app_module
import db
import rag_engine

FIREWALL_BODY = "open a port through the firewall to reach the service"
MULTIGRID_BODY = "coarse space near null algebraic multigrid"


def _add(client, auth, title, body, edges=None):
    payload = {"title": title, "body": body}
    if edges:
        payload["edges"] = edges
    r = client.post("/ideas", json=payload, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_search_requires_auth(client):
    r = client.post("/search", json={"query": "firewall port"})
    assert r.status_code == 401


def test_empty_store_returns_no_results(client, auth):
    r = client.post("/search", json={"query": "firewall port"}, headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body == {"query": "firewall port", "results": [], "context": ""}


def test_vector_seed_matches_query(client, auth):
    fid = _add(client, auth, "Firewall", FIREWALL_BODY)
    _add(client, auth, "Trees", "give a tree model arithmetic via feature engineering")

    body = client.post(
        "/search",
        json={"query": "firewall port service", "start_k": 1, "hops": 0},
        headers=auth,
    ).json()

    assert [h["id"] for h in body["results"]] == [fid]
    hit = body["results"][0]
    assert hit["depth"] == 0
    assert hit["score"] > 0
    assert hit["reason"] == "vector seed"
    assert "Firewall" in body["context"]


def test_embed_on_write_persists_vector(client, auth):
    fid = _add(client, auth, "Firewall", FIREWALL_BODY)
    conn = db.connect()
    try:
        row = db.fetch_idea(conn, fid)
    finally:
        conn.close()
    assert row["embedding"] is not None
    assert row["embedding_model"] == app_module.rag.model_name
    assert row["embedding_dim"] == app_module.rag.dim


def test_hops_pull_in_linked_idea(client, auth):
    # An idea whose text does NOT match the query is still surfaced via a link.
    fid = _add(client, auth, "Firewall", FIREWALL_BODY)
    mid = _add(
        client, auth, "Multigrid", MULTIGRID_BODY,
        edges=[{"target_id": fid, "type": "connected", "note": "linked by hand"}],
    )
    q = {"query": "firewall port service", "start_k": 1}

    r0 = client.post("/search", json={**q, "hops": 0}, headers=auth).json()
    assert [h["id"] for h in r0["results"]] == [fid]  # pure vector: only the seed

    r1 = client.post("/search", json={**q, "hops": 1}, headers=auth).json()
    got = {h["id"]: h for h in r1["results"]}
    assert fid in got and mid in got
    assert got[fid]["depth"] == 0
    assert got[mid]["depth"] == 1
    assert got[mid]["score"] is None
    assert "connected" in got[mid]["reason"]


def test_traversal_forward_direction(client, auth):
    # Edge source=B, target=A. Seeding B (source) reaches A (target) — forward.
    aid = _add(client, auth, "Firewall", FIREWALL_BODY)
    bid = _add(
        client, auth, "Multigrid", MULTIGRID_BODY,
        edges=[{"target_id": aid, "type": "connected", "note": "x"}],
    )
    r = client.post(
        "/search",
        json={"query": "coarse algebraic multigrid", "start_k": 1, "hops": 1},
        headers=auth,
    ).json()
    got = {h["id"]: h["depth"] for h in r["results"]}
    assert got.get(bid) == 0
    assert got.get(aid) == 1  # reached across the edge in its declared direction


def test_update_reembeds(client, auth):
    iid = _add(client, auth, "Note", MULTIGRID_BODY)

    before = client.post(
        "/search",
        json={"query": "algebraic multigrid coarse", "start_k": 1, "hops": 0},
        headers=auth,
    ).json()
    assert before["results"][0]["id"] == iid and before["results"][0]["score"] > 0

    up = client.patch(f"/ideas/{iid}", json={"body": FIREWALL_BODY}, headers=auth)
    assert up.status_code == 200

    # Now it matches a firewall query...
    firewall = client.post(
        "/search",
        json={"query": "firewall port service", "start_k": 1, "hops": 0},
        headers=auth,
    ).json()
    assert firewall["results"][0]["id"] == iid and firewall["results"][0]["score"] > 0

    # ...and no longer the multigrid one (re-embedded to the other cluster).
    multigrid = client.post(
        "/search",
        json={"query": "algebraic multigrid coarse", "start_k": 5, "hops": 0},
        headers=auth,
    ).json()
    assert multigrid["results"][0]["score"] == 0.0


def test_delete_removes_from_index(client, auth):
    iid = _add(client, auth, "Firewall", FIREWALL_BODY)
    assert client.delete(f"/ideas/{iid}", headers=auth).status_code == 200
    r = client.post("/search", json={"query": "firewall port service"}, headers=auth).json()
    assert r["results"] == []


def test_disabled_returns_503(client, auth):
    app_module.rag.enabled = False
    r = client.post("/search", json={"query": "firewall"}, headers=auth)
    assert r.status_code == 503
    assert r.json()["error"] == "rag_disabled"


def test_index_idea_embeds_current_committed_text(client, auth):
    """index_idea re-reads the idea's CURRENT committed text from the DB rather
    than trusting stale caller-supplied text — so a persisted/warm vector can never
    drift out of sync with the row (regression: a slow concurrent PATCH's re-embed
    landing last would otherwise leave the older text's vector on the newer row)."""
    iid = _add(client, auth, "Note", MULTIGRID_BODY)
    # Commit a new body directly, bypassing the endpoint's own re-embed path.
    conn = db.connect()
    try:
        conn.execute("UPDATE ideas SET body = ? WHERE id = ?", (FIREWALL_BODY, iid))
    finally:
        conn.close()

    app_module.rag.index_idea(iid)  # id only: must embed the firewall text now in the DB

    hit = client.post(
        "/search",
        json={"query": "firewall port service", "start_k": 1, "hops": 0},
        headers=auth,
    ).json()["results"][0]
    assert hit["id"] == iid and hit["score"] > 0


class _SpyEmbedder:
    """Records the is_query flag of every encode call so a test can assert that
    documents are embedded bare while queries carry the query flag."""

    dim = 4

    def __init__(self):
        self.calls = []  # list of (is_query, [texts])

    def encode(self, texts, is_query=False):
        texts = list(texts)
        self.calls.append((is_query, texts))
        vecs = np.ones((len(texts), self.dim), dtype=np.float32)
        return vecs / np.linalg.norm(vecs, axis=1, keepdims=True)


def test_query_encoded_as_query_documents_encoded_bare():
    """Retrieval must encode the QUERY with is_query=True while the write-path /
    backfill encodes stay bare. An asymmetric model (e.g. arctic-embed) needs its
    query prompt only on the query side; without this wiring it embeds queries as
    documents and silently regresses. Symmetric models ignore the flag, so this
    locks the contract in regardless of which model is configured."""
    conn = db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        db.insert_idea(conn, "spy-1", {"title": "Firewall", "body": FIREWALL_BODY}, db.now_iso())
        conn.execute("COMMIT")
    finally:
        conn.close()

    engine = rag_engine.RagEngine(model_name="spy")
    engine.set_embedder(_SpyEmbedder())
    spy = engine._embedder

    conn = db.connect()
    try:
        engine.backfill(conn)                     # document encode
        engine.search(conn, "firewall port")      # query encode
    finally:
        conn.close()

    query_flags = [is_q for is_q, texts in spy.calls if "firewall port" in texts]
    assert query_flags == [True], "the search query was not encoded with is_query=True"
    doc_flags = [is_q for is_q, texts in spy.calls if any(FIREWALL_BODY in t for t in texts)]
    assert doc_flags and all(f is False for f in doc_flags), "documents must be embedded bare"


class _StubModel:
    """A SentenceTransformer stand-in that records which prompt each encode used."""

    def __init__(self, prompts):
        self.prompts = prompts
        self.seen_prompt = []

    def encode(self, texts, **kwargs):
        self.seen_prompt.append(kwargs.get("prompt_name"))
        return np.zeros((len(list(texts)), 3), dtype=np.float32)

    def get_sentence_embedding_dimension(self):
        return 3


def _embedder_with(prompts):
    emb = object.__new__(rag_engine.SentenceTransformerEmbedder)
    emb.model_name = "stub"
    emb._model = _StubModel(prompts)
    emb.dim = 3
    return emb


def test_embedder_applies_query_prompt_only_for_queries_when_model_defines_one():
    emb = _embedder_with({"query": "Represent this sentence for searching relevant passages: "})
    emb.encode(["a document"], is_query=False)
    emb.encode(["a query"], is_query=True)
    assert emb._model.seen_prompt == [None, "query"]


def test_embedder_ignores_query_flag_when_model_has_no_query_prompt():
    emb = _embedder_with({})  # MiniLM-style symmetric model: no query prompt to apply
    emb.encode(["a document"], is_query=False)
    emb.encode(["a query"], is_query=True)
    assert emb._model.seen_prompt == [None, None]


def test_load_persisted_skips_dim_mismatched_blob():
    """A persisted BLOB whose byte length disagrees with its stored embedding_dim
    is quarantined, not adopted — otherwise a corrupt row could set the whole
    index's dimension and 500 every subsequent query."""
    iid = "corrupt-vector"
    conn = db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        db.insert_idea(conn, iid, {"title": "Corrupt", "body": "x"}, db.now_iso())
        bad_blob = np.zeros(3, dtype=np.float32).tobytes()  # 3 floats...
        db.set_embedding(conn, iid, bad_blob, rag_engine.DEFAULT_MODEL, 27)  # ...claims dim 27
        conn.execute("COMMIT")
    finally:
        conn.close()

    engine = rag_engine.RagEngine(model_name=rag_engine.DEFAULT_MODEL)  # no embedder → dim unset
    conn = db.connect()
    try:
        loaded = engine.load_persisted(conn)
    finally:
        conn.close()
    assert loaded == 0
    assert iid not in engine._vecs
