"""GraphRAG over IdeaL: vector-seed + wikilink traversal, wrapped in LangGraph.

Engine = LangChain's first-party ``GraphRetriever`` (vector similarity picks seeds, then it
traverses the ``[[target-id]]`` edges). The LangGraph ``StateGraph`` is a thin, deterministic
``retrieve → format`` wrapper — retrieve-only, no LLM. The retrieved block is the result; read it
or hand it to Claude.

CLI:  python -m rag.search "your semantic query" [--k 8] [--start-k 4] [--hops 1] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import TypedDict

from graph_retriever.strategies import Eager
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_graph_retriever import GraphRetriever
from langgraph.graph import END, START, StateGraph

from .store import EDGES, to_documents

DEFAULT_CLIENT = os.environ.get(
    "IDEAL_CLIENT",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "skills", "ideal", "scripts", "ideal.py"),
)


def build_retriever(documents, embeddings, *, k=8, start_k=4, max_depth=1) -> GraphRetriever:
    """In-memory vector store over the documents + the graph retriever with undirected edges."""
    store = InMemoryVectorStore(embedding=embeddings)
    store.add_documents(documents)
    return GraphRetriever(
        store=store, edges=EDGES,
        strategy=Eager(k=k, start_k=start_k, max_depth=max_depth),
    )


class RagState(TypedDict, total=False):
    query: str
    documents: list  # List[Document], seeds (depth 0) first then traversed neighbours
    context: str     # assembled markdown block


def build_app(retriever: GraphRetriever):
    """Compile the LangGraph app: START → retrieve → format → END."""

    def retrieve(state: RagState):
        return {"documents": retriever.invoke(state["query"])}

    def format_context(state: RagState):
        return {"context": render(state.get("documents", []))}

    g = StateGraph(RagState)
    g.add_node("retrieve", retrieve)
    g.add_node("format", format_context)
    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "format")
    g.add_edge("format", END)
    return g.compile()


def render(documents) -> str:
    """Render retrieved documents as a ranked markdown block, tagged with why each is here."""
    blocks = []
    for d in documents:
        m = d.metadata
        depth = m.get("_depth", 0)
        score = m.get("_similarity_score")
        meta = [f"`{m.get('id')}`"]
        if depth == 0:
            meta.append(f"seed · score {float(score):.3f}" if score is not None else "seed")
        else:
            meta.append(f"reached · {depth} hop{'s' if depth != 1 else ''} out")
        if m.get("tags"):
            meta.append("tags: " + ", ".join(m["tags"]))
        paper = m.get("paper")
        if paper and paper.get("s"):
            meta.append(str(paper["s"]))
        title = m.get("title") or d.id
        body = m.get("body") or d.page_content
        blocks.append(f"### {title}\n{' · '.join(meta)}\n\n{body}")
    return "\n\n".join(blocks).strip()


def load_documents(client: str = DEFAULT_CLIENT) -> list:
    """Fetch the store via ``ideal.py export --format json`` and map it to documents."""
    out = subprocess.run(
        [sys.executable, client, "export", "--format", "json"],
        check=True, capture_output=True, text=True,
    ).stdout
    return to_documents(json.loads(out))


def search(query: str, *, documents, embeddings, k: int = 8, start_k: int = 4, hops: int = 1) -> dict:
    """Run the LangGraph pipeline; return {query, results, context}."""
    app = build_app(build_retriever(documents, embeddings, k=k, start_k=start_k, max_depth=hops))
    state = app.invoke({"query": query})
    docs = state.get("documents", [])
    results = []
    for d in docs:
        s = d.metadata.get("_similarity_score")
        results.append({
            "id": d.metadata.get("id"),
            "title": d.metadata.get("title"),
            "depth": d.metadata.get("_depth", 0),
            "score": float(s) if s is not None else None,
        })
    return {"query": query, "results": results, "context": state.get("context", "")}


def _format_human(res: dict) -> str:
    seeds = sum(1 for r in res["results"] if r["depth"] == 0)
    lines = [f"{len(res['results'])} ideas retrieved ({seeds} seeds + graph neighbours)\n"]
    for r in res["results"]:
        tag = (f"seed {r['score']:.3f}" if r["depth"] == 0 and r["score"] is not None
               else "seed" if r["depth"] == 0 else f"hop {r['depth']}")
        lines.append(f"  [{tag}] {r['title']}")
        lines.append(f"        {r['id']}")
    lines.append("\n--- context block ---\n")
    lines.append(res["context"])
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="rag.search", description="GraphRAG over IdeaL")
    ap.add_argument("query", help="natural-language query")
    ap.add_argument("--k", type=int, default=8, help="total ideas to return (default 8)")
    ap.add_argument("--start-k", type=int, default=4, help="vector seed count (default 4)")
    ap.add_argument("--hops", type=int, default=1, help="graph traversal depth (default 1)")
    ap.add_argument("--json", action="store_true", help="emit raw JSON instead of text")
    ap.add_argument("--client", default=DEFAULT_CLIENT, help="path to ideal.py")
    args = ap.parse_args(argv)

    from .embedder import MiniLMEmbeddings  # heavy import only when actually running

    documents = load_documents(args.client)
    res = search(args.query, documents=documents, embeddings=MiniLMEmbeddings(),
                 k=args.k, start_k=args.start_k, hops=args.hops)
    print(json.dumps(res, ensure_ascii=False, indent=2) if args.json else _format_human(res))


if __name__ == "__main__":
    main()
