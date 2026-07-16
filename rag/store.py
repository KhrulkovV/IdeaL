"""Parse the JSON export into LangChain ``Document``s for the graph retriever.

Each idea becomes one ``Document`` whose ``page_content`` is what gets embedded
(``title`` + ``body``) and whose metadata carries the explicit ``[[target-id]]`` wikilinks
as id lists, split by edge type. ``GraphRetriever`` then traverses those id lists directly
(``("connected_to", "$id")`` etc.) — no adjacency to precompute here; the retriever owns
traversal. Dangling targets (ids not in the store) are dropped so rendering never dereferences
a missing idea.
"""
from __future__ import annotations

import json
from typing import Optional

from langchain_core.documents import Document

# Edge spec handed to GraphRetriever. Each type is listed in BOTH directions so traversal is
# undirected: ("connected_to", "$id") follows this idea's outgoing links; ("$id", "connected_to")
# follows incoming links (ideas whose connected_to list names this idea). IdeaL stores edges
# directed/outgoing; retrieval wants the whole ego-network regardless of which way Claude wrote it.
EDGES = [
    ("connected_to", "$id"), ("$id", "connected_to"),
    ("similar_to", "$id"), ("$id", "similar_to"),
]

_TYPE_FIELD = {"connected": "connected_to", "similar": "similar_to"}


def compact_paper(meta) -> Optional[dict]:
    """Compact an idea's ``meta`` blob into short-keyed paper provenance, or None."""
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            return None
    if not isinstance(meta, dict):
        return None
    p = {k: meta.get(src) for k, src in (
        ("s", "source"), ("t", "title"), ("a", "authors"), ("y", "year"), ("u", "url"),
    )}
    return p if any(v is not None for v in p.values()) else None


def to_documents(data: dict) -> list[Document]:
    """Build the retriever's ``Document`` list from a ``GET /export?format=json`` payload."""
    raw = data.get("ideas", [])
    known = {it["id"] for it in raw}
    docs: list[Document] = []
    for it in raw:
        links = {"connected_to": [], "similar_to": []}
        for e in (it.get("links_out") or []):
            field = _TYPE_FIELD.get(e.get("type", "connected"), "connected_to")
            tgt = e.get("target_id")
            if tgt in known and tgt not in links[field]:
                links[field].append(tgt)
        title = it.get("title", "")
        body = it.get("body", "")
        docs.append(Document(
            id=it["id"],
            page_content=f"{title}\n\n{body}".strip(),
            metadata={
                "id": it["id"],
                "title": title,
                "body": body,
                "tags": list(it.get("tags") or []),
                "paper": compact_paper(it.get("meta")),
                **links,
            },
        ))
    return docs
