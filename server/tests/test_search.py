"""POST /search — the optional server-side GraphRAG. Uses the FakeEmbedder
injected in conftest, so no torch/model is needed.

Vocabulary the fake understands (see conftest): a "firewall/port/service" cluster
and a disjoint "coarse/algebraic/multigrid" cluster, so a query in one cluster
scores ~0 on ideas from the other.
"""
import app as app_module
import db

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
