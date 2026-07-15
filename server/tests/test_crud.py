"""Behavior tests for the Update + Delete half of CRUD (ideas and links).

Exercised through the public HTTP surface, like test_api.py.
"""


def _add(client, auth, **body):
    return client.post("/ideas", json=body, headers=auth).json()["id"]


# --- delete idea -------------------------------------------------------------

def test_delete_idea_removes_it(client, auth):
    idea_id = _add(client, auth, title="Delete me", body="x")
    r = client.delete(f"/ideas/{idea_id}", headers=auth)
    assert r.status_code == 200
    assert r.json()["deleted"] == idea_id

    assert client.get(f"/ideas/{idea_id}", headers=auth).status_code == 404
    assert client.get("/health").json()["ideas"] == 0


def test_delete_idea_cascades_its_links(client, auth):
    a = _add(client, auth, title="Cascade A", body="x")
    b = _add(client, auth, title="Cascade B", body="y",
             edges=[{"target_id": a, "type": "connected", "note": "b->a"}])
    assert client.get("/health").json()["links"] == 1

    assert client.delete(f"/ideas/{a}", headers=auth).status_code == 200

    # the edge b->a is gone; b itself survives with no outgoing links.
    assert client.get("/health").json()["links"] == 0
    view_b = client.get(f"/ideas/{b}", headers=auth).json()
    assert view_b["links_out"] == []


def test_delete_unknown_idea_is_404(client, auth):
    r = client.delete("/ideas/nope", headers=auth)
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"


def test_delete_requires_token(client, auth):
    idea_id = _add(client, auth, title="Guarded", body="x")
    assert client.delete(f"/ideas/{idea_id}").status_code == 401
    # still there after the unauthorized attempt
    assert client.get(f"/ideas/{idea_id}", headers=auth).status_code == 200


# --- update idea -------------------------------------------------------------

def test_update_changes_a_field(client, auth):
    idea_id = _add(client, auth, title="Original", body="old body")
    r = client.patch(f"/ideas/{idea_id}", json={"body": "new body"}, headers=auth)
    assert r.status_code == 200
    assert r.json()["body"] == "new body"

    view = client.get(f"/ideas/{idea_id}", headers=auth).json()
    assert view["body"] == "new body"
    assert view["title"] == "Original"  # untouched


def test_update_is_partial_and_keeps_other_fields(client, auth):
    idea_id = _add(client, auth, title="Keep", body="b", tags=["one", "two"])
    client.patch(f"/ideas/{idea_id}", json={"title": "Renamed"}, headers=auth)

    view = client.get(f"/ideas/{idea_id}", headers=auth).json()
    assert view["title"] == "Renamed"
    assert view["tags"] == ["one", "two"]  # not wiped by the partial update


def test_update_does_not_change_the_id(client, auth):
    idea_id = _add(client, auth, title="Stable Slug", body="b")
    assert idea_id == "stable-slug"
    client.patch(f"/ideas/{idea_id}", json={"title": "A Totally New Title"}, headers=auth)
    # id is immutable even though the title changed
    assert client.get(f"/ideas/{idea_id}", headers=auth).json()["title"] == "A Totally New Title"
    assert client.get("/ideas/a-totally-new-title", headers=auth).status_code == 404


def test_update_can_set_and_clear_a_nullable_field(client, auth):
    idea_id = _add(client, auth, title="Meta", body="b")
    client.patch(f"/ideas/{idea_id}", json={"usefulness": 80}, headers=auth)
    assert client.get(f"/ideas/{idea_id}", headers=auth).json()["usefulness"] == 80

    # explicit null clears it (distinct from omitting the key)
    client.patch(f"/ideas/{idea_id}", json={"usefulness": None}, headers=auth)
    assert client.get(f"/ideas/{idea_id}", headers=auth).json()["usefulness"] is None


def test_update_rejects_empty_title(client, auth):
    idea_id = _add(client, auth, title="Nonempty", body="b")
    r = client.patch(f"/ideas/{idea_id}", json={"title": "   "}, headers=auth)
    assert r.status_code == 422


def test_update_unknown_idea_is_404(client, auth):
    r = client.patch("/ideas/nope", json={"body": "x"}, headers=auth)
    assert r.status_code == 404


def test_update_requires_token(client, auth):
    idea_id = _add(client, auth, title="Guarded2", body="x")
    assert client.patch(f"/ideas/{idea_id}", json={"body": "z"}).status_code == 401


# --- delete link -------------------------------------------------------------

def test_delete_link_removes_only_that_edge(client, auth):
    a = _add(client, auth, title="Link A", body="x")
    b = _add(client, auth, title="Link B", body="y",
             edges=[{"target_id": a, "type": "connected", "note": "n"}])

    r = client.request("DELETE", "/links", headers=auth,
                       json={"source_id": b, "target_id": a, "type": "connected"})
    assert r.status_code == 200
    assert r.json()["deleted"] is True

    assert client.get("/health").json()["links"] == 0
    # both ideas still exist
    assert client.get(f"/ideas/{a}", headers=auth).status_code == 200
    assert client.get(f"/ideas/{b}", headers=auth).status_code == 200


def test_delete_missing_link_reports_false(client, auth):
    a = _add(client, auth, title="NL A", body="x")
    b = _add(client, auth, title="NL B", body="y")
    r = client.request("DELETE", "/links", headers=auth,
                       json={"source_id": a, "target_id": b, "type": "similar"})
    assert r.status_code == 200
    assert r.json()["deleted"] is False
