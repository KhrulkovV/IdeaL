"""Export JSON → LangChain Documents: content, link-id metadata, provenance compaction."""
from rag.store import compact_paper, to_documents


def _by_id(documents):
    return {d.id: d for d in documents}


def test_one_document_per_idea_with_embedded_content(documents):
    assert len(documents) == 4
    fw = _by_id(documents)["firewall-two-layers"]
    # page_content (what gets embedded) is title + body
    assert fw.page_content.startswith("Two firewall layers")
    assert "cloud firewall" in fw.page_content


def test_links_split_by_edge_type(documents):
    fw = _by_id(documents)["firewall-two-layers"]
    assert fw.metadata["connected_to"] == ["ssh-tunnel"]
    assert fw.metadata["similar_to"] == []


def test_similar_edges_land_in_similar_field():
    docs = to_documents({"ideas": [
        {"id": "a", "title": "A", "body": "x",
         "links_out": [{"target_id": "b", "type": "similar"}]},
        {"id": "b", "title": "B", "body": "y"},
    ]})
    a = _by_id(docs)["a"]
    assert a.metadata["similar_to"] == ["b"]
    assert a.metadata["connected_to"] == []


def test_dangling_targets_are_dropped(documents):
    # firewall-two-layers links to a non-existent 'ghost' id
    fw = _by_id(documents)["firewall-two-layers"]
    assert "ghost" not in fw.metadata["connected_to"]


def test_metadata_carries_id_tags_and_paper(documents):
    fw = _by_id(documents)["firewall-two-layers"]
    assert fw.metadata["id"] == "firewall-two-layers"
    assert fw.metadata["tags"] == ["firewall"]
    assert fw.metadata["paper"]["s"] == "arXiv:1234.5678"
    assert _by_id(documents)["ssh-tunnel"].metadata["paper"] is None


def test_compact_paper_handles_dict_str_and_none():
    d = {"source": "arXiv:1", "title": "P", "authors": "X", "year": 2023, "url": "u"}
    assert compact_paper(d)["s"] == "arXiv:1"
    assert compact_paper('{"source": "arXiv:2"}')["s"] == "arXiv:2"
    assert compact_paper(None) is None
    assert compact_paper("not json") is None
    assert compact_paper({}) is None
