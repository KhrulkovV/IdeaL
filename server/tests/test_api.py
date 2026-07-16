"""Behavior tests for the IdeaL API, exercised through the public HTTP surface."""
from export import render_markdown


# --- health / auth -----------------------------------------------------------

def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["ideas"] == 0 and body["links"] == 0


def test_write_rejected_without_token(client):
    r = client.post("/ideas", json={"title": "x", "body": "y"})
    assert r.status_code == 401


def test_write_rejected_with_bad_token(client):
    r = client.post(
        "/ideas", json={"title": "x", "body": "y"},
        headers={"Authorization": "Bearer wrong"},
    )
    assert r.status_code == 401


def test_export_read_requires_token_when_protected(client):
    assert client.get("/export").status_code == 401


# --- add + export ------------------------------------------------------------

def test_add_idea_appears_in_export(client, auth):
    r = client.post(
        "/ideas",
        json={"title": "Ideas as a graph", "body": "Atoms and edges."},
        headers=auth,
    )
    assert r.status_code == 201
    idea_id = r.json()["id"]
    assert idea_id == "ideas-as-a-graph"

    text = client.get("/export", headers=auth).text
    assert "Ideas as a graph" in text
    assert f"`{idea_id}`" in text
    assert "Atoms and edges." in text
    assert "usefulness: —" in text  # null metadata rendered as em-dash


def test_add_edge_shows_in_export(client, auth):
    a = client.post("/ideas", json={"title": "Idea A", "body": "First."}, headers=auth).json()["id"]
    resp = client.post(
        "/ideas",
        json={
            "title": "Idea B",
            "body": "Second.",
            "edges": [{"target_id": a, "type": "connected", "note": "builds on A"}],
        },
        headers=auth,
    )
    assert resp.status_code == 201
    assert resp.json()["edges_created"] == 1

    text = client.get("/export", headers=auth).text
    assert f"[[{a}]]" in text
    assert "**connected**" in text
    assert "builds on A" in text


# --- unknown targets ---------------------------------------------------------

def test_unknown_target_rejected_and_rolled_back(client, auth):
    r = client.post(
        "/ideas",
        json={
            "title": "Dangling",
            "body": "x",
            "edges": [{"target_id": "does-not-exist", "type": "similar", "note": "n"}],
        },
        headers=auth,
    )
    assert r.status_code == 422
    assert r.json()["error"] == "unknown_targets"

    ideas = client.get("/ideas", headers=auth).json()["ideas"]
    assert all(i["title"] != "Dangling" for i in ideas)  # not created


def test_unknown_target_ignore_mode_creates_without_edge(client, auth):
    r = client.post(
        "/ideas?on_unknown_target=ignore",
        json={
            "title": "Solo",
            "body": "x",
            "edges": [{"target_id": "nope", "type": "similar", "note": "n"}],
        },
        headers=auth,
    )
    assert r.status_code == 201
    assert r.json()["edges_created"] == 0
    assert "nope" in r.json()["edges_ignored"]


# --- links endpoint / idempotency -------------------------------------------

def test_link_endpoint_is_idempotent(client, auth):
    a = client.post("/ideas", json={"title": "L A", "body": "x"}, headers=auth).json()["id"]
    b = client.post("/ideas", json={"title": "L B", "body": "y"}, headers=auth).json()["id"]
    edge = {"source_id": a, "target_id": b, "type": "similar", "note": "n"}

    first = client.post("/links", json=edge, headers=auth)
    assert first.status_code == 201 and first.json()["created"] is True

    second = client.post("/links", json=edge, headers=auth)
    assert second.status_code == 201 and second.json()["created"] is False


# --- score bounds ------------------------------------------------------------

def test_out_of_range_score_rejected_on_create(client, auth):
    r = client.post(
        "/ideas",
        json={"title": "Scored", "body": "x", "reputation": 101},
        headers=auth,
    )
    assert r.status_code == 422


def test_out_of_range_score_rejected_on_update(client, auth):
    iid = client.post("/ideas", json={"title": "S", "body": "x"}, headers=auth).json()["id"]
    r = client.patch(f"/ideas/{iid}", json={"usefulness": -1}, headers=auth)
    assert r.status_code == 422


def test_in_range_score_accepted(client, auth):
    iid = client.post(
        "/ideas", json={"title": "S2", "body": "x", "usefulness": 0, "reputation": 100},
        headers=auth,
    ).json()["id"]
    view = client.get(f"/ideas/{iid}", headers=auth).json()
    assert view["usefulness"] == 0 and view["reputation"] == 100


# --- ids ---------------------------------------------------------------------

def test_duplicate_titles_get_numeric_suffix(client, auth):
    id1 = client.post("/ideas", json={"title": "Same Title", "body": "one"}, headers=auth).json()["id"]
    id2 = client.post("/ideas", json={"title": "Same Title", "body": "two"}, headers=auth).json()["id"]
    assert id1 == "same-title"
    assert id2 == "same-title-2"


# --- single idea view --------------------------------------------------------

def test_get_idea_reports_in_and_out_links(client, auth):
    a = client.post("/ideas", json={"title": "GA", "body": "x"}, headers=auth).json()["id"]
    b = client.post(
        "/ideas",
        json={"title": "GB", "body": "y", "edges": [{"target_id": a, "type": "similar", "note": "same"}]},
        headers=auth,
    ).json()["id"]

    view_a = client.get(f"/ideas/{a}", headers=auth).json()
    assert any(l["source_id"] == b for l in view_a["links_in"])

    view_b = client.get(f"/ideas/{b}", headers=auth).json()
    assert any(l["target_id"] == a for l in view_b["links_out"])


def test_get_missing_idea_is_404(client, auth):
    r = client.get("/ideas/nope", headers=auth)
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"


# --- pure render unit test ---------------------------------------------------

def test_render_markdown_line_format():
    ideas = [{
        "id": "a", "title": "A", "body": "Body A", "author": "alice",
        "tags": "x,y", "task": None, "usefulness": None, "reputation": None,
        "status": "draft", "created_at": "2026-07-15T00:00:00Z",
        "updated_at": "2026-07-15T00:00:00Z",
    }]
    links = [{"source_id": "a", "target_id": "b", "type": "similar", "note": "dup"}]
    md = render_markdown(ideas, links, "2026-07-15T00:00:00Z")

    assert "idea_count: 1" in md
    assert "link_count: 1" in md
    assert "## A" in md
    assert "`a` · alice · tags: x, y" in md
    assert "status: draft" in md  # lifecycle status is visible in the read surface
    assert "- **similar** → [[b]] — dup" in md
