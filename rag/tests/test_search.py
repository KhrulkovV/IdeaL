"""GraphRAG wiring: vector seeds, undirected edge traversal, and render format.

Uses the fake Embeddings, so the GraphRetriever runs with no torch/network. The behaviour under
test is the whole point of the layer: an idea whose own text doesn't match the query is still
retrieved when a wikilink connects it to a seed.
"""
from rag.search import render, search


def _ids(res):
    return [r["id"] for r in res["results"]]


def test_hops_0_is_plain_vector_search(documents, embeddings):
    # 'firewall port' matches firewall-two-layers; ssh-tunnel shares no query words.
    res = search("firewall port", documents=documents, embeddings=embeddings,
                 k=5, start_k=1, hops=0)
    assert "firewall-two-layers" in _ids(res)
    assert "ssh-tunnel" not in _ids(res)


def test_traversal_pulls_in_linked_idea_that_did_not_match(documents, embeddings):
    res = search("firewall port", documents=documents, embeddings=embeddings,
                 k=5, start_k=1, hops=1)
    ids = _ids(res)
    assert "firewall-two-layers" in ids  # the seed
    assert "ssh-tunnel" in ids           # reached only via the connected edge


def test_traversal_is_undirected(documents, embeddings):
    # Seed on ssh-tunnel's words; it has no outgoing links, but firewall-two-layers links TO it,
    # so the reverse edge must still surface firewall-two-layers.
    res = search("ssh tunnel", documents=documents, embeddings=embeddings,
                 k=5, start_k=1, hops=1)
    assert "firewall-two-layers" in _ids(res)


def test_result_records_depth_and_score(documents, embeddings):
    res = search("firewall port", documents=documents, embeddings=embeddings,
                 k=5, start_k=1, hops=1)
    seed = next(r for r in res["results"] if r["id"] == "firewall-two-layers")
    hopped = next(r for r in res["results"] if r["id"] == "ssh-tunnel")
    assert seed["depth"] == 0 and seed["score"] is not None
    assert hopped["depth"] == 1


def test_render_tags_seed_vs_reached_and_shows_provenance(documents, embeddings):
    res = search("firewall port", documents=documents, embeddings=embeddings,
                 k=5, start_k=1, hops=1)
    block = res["context"]
    assert "### Two firewall layers" in block
    assert "seed ·" in block
    assert "arXiv:1234.5678" in block          # paper provenance surfaced
    assert "hop out" in block                  # the reached neighbour is labelled


def test_render_empty_is_empty_string():
    assert render([]) == ""
