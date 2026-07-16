# IdeaL — GraphRAG retrieval layer (additive, canonical LangChain component)

> **⚠️ Superseded / removed.** This describes the *client-side* `rag/` package, which has been
> **removed**. Retrieval now runs **server-side**: the server embeds each idea on write and answers
> `POST /search`, so clients need only Python stdlib. See `2026-07-16-server-side-rag-design.md` for
> the shipped design. This document is retained for historical context only.

## Intent & the constraint it bends

IdeaL was built **without** embeddings/RAG on purpose: the store is dumb, and Claude reads the
whole exported markdown and reasons. This feature adds an **optional, read-side** semantic
retrieval layer *on top of* that — for when you want a relevant sub-slice by query instead of
dumping the entire store into context. It does **not** replace the reason-over-everything ADD/link
flow, and it adds **nothing** to the server.

## Decision: use the official component, don't hand-roll

Per the directive "no need to reinvent the wheel," this uses LangChain's **dedicated Graph RAG
retriever** rather than a custom cosine+BFS pipeline.

- **Package:** [`langchain-graph-retriever`](https://docs.langchain.com/oss/python/integrations/retrievers/graph_rag)
  — a first-party LangChain retriever that "combines unstructured similarity search on vectors with
  structured traversal of metadata properties." This *is* basic GraphRAG: vector seed → traverse
  edges. It replaces the hand-rolled `index.py` (cosine) and `graph.py` (BFS) entirely.
- **The exact fit:** its `$id`-targeted edges follow explicit document links by id — e.g.
  `("links_to", "$id")` means "take the id list in this doc's `links_to` field and traverse to the
  docs with those ids." That is precisely IdeaL's `[[target-id]]` wikilink model (not the weaker
  shared-metadata-value edges like `("tags","tags")`).

### Reference pattern (from the official docs)

```python
from langchain_graph_retriever import GraphRetriever
from graph_retriever.strategies import Eager

retriever = GraphRetriever(
    store=vector_store,
    edges=[("connected_to", "$id"), ("similar_to", "$id")],  # follow IdeaL wikilinks by id
    strategy=Eager(k=8, start_k=4, max_depth=1),             # start_k seeds, max_depth hops
)
results = retriever.invoke("your semantic query")            # -> List[Document]
```

`start_k` = seed docs from similarity search; `max_depth` = hops along edges (0 ⇒ plain vector
search, no traversal); `k` = total docs returned. Strategy `Eager` (breadth-first) or `Mmr`
(diversity). This maps 1:1 onto the `--k`/`--hops` CLI we already sketched.

## Where it lives

A client-side package `rag/` (sibling to `server/`), invoked where Claude Code runs. It pulls the
store via the existing `skills/ideal/scripts/ideal.py export --format json` (reuses config/auth in
`~/.config/ideal/config.env`). Server, plugin, and snapshot tooling are untouched.

```
IdeaL/rag/
├── store.py       # parse JSON export → List[langchain_core.documents.Document]
│                  #   page_content = "title\n\nbody"
│                  #   metadata = {id, connected_to:[ids], similar_to:[ids], tags, paper, title}
├── embedder.py    # sentence-transformers MiniLM wrapped as a langchain_core Embeddings
├── search.py      # build InMemoryVectorStore + GraphRetriever; LangGraph wrapper; CLI
│                  #   python -m rag.search "query" [--k 8] [--start-k 4] [--hops 1] [--json]
├── requirements.txt
└── tests/         # pure tests: export→Document mapping; a FakeEmbeddings for retriever wiring
```

`index.py` and the hand-rolled `graph.py` are **deleted** — the retriever owns embedding, cosine,
and traversal.

## Vector store

`langchain_core.vectorstores.InMemoryVectorStore` (already installed, no extra DB). It stores
list-valued metadata as-is, so `$id` link edges work without the "shredding" that Chroma/Astra need
for list fields. Building it in-memory each run matches IdeaL's "hold the whole store" philosophy;
the store is small (order 10²–10³ ideas). Embeddings are recomputed per run initially; an optional
persisted `InMemoryVectorStore.dump()/load()` cache keyed off the export can come later if latency
warrants — not needed for correctness.

## Embedder

sentence-transformers **all-MiniLM-L6-v2** (confirmed choice) exposed through the `Embeddings`
interface so the vector store and retriever accept it directly. Model id overridable via
`IDEAL_RAG_MODEL`.

## LangGraph shape (retrieve-only — no LLM)

The retrieve-only choice means we do **not** use the full Agentic-RAG tutorial graph (which uses an
LLM to decide-to-retrieve / grade / generate an answer). Instead the LangGraph layer is a thin
deterministic `StateGraph` that wraps the canonical retriever:

`START → retrieve (GraphRetriever.invoke) → format (render Documents to a ranked markdown block) → END`

State `{query, k, start_k, hops, documents, context}`. This keeps "LangGraph-based" true to the
ask while the GraphRAG engine itself is the first-party `GraphRetriever`. If prose-answer synthesis
is ever wanted, it becomes one added `generate` node following the Agentic-RAG tutorial — out of
scope now.

## Output format

Each returned `Document` renders as a markdown block: title, `` `id` ``, why-it's-here (seed vs
reached via edge), tags, and paper provenance (`meta.source`) when present — same shape the snapshot
already uses. That block is the retrieval result; feed it to Claude or read it directly.

## Testing (test-first for the non-trivial logic)

- **`store.py` (pure, no torch):** export JSON → `Document` list; verify `page_content`, and that
  `connected_to`/`similar_to` metadata hold the right target-id lists (dropping ids not in the
  store), tags, and compacted paper meta. This is where our bugs would live now that the retriever
  owns similarity/traversal.
- **Retriever wiring (FakeEmbeddings):** a deterministic bag-of-words `Embeddings` stub lets us
  assert end-to-end that a query sharing words with a seed returns it, and that a linked neighbor
  with non-matching text is pulled in at `max_depth=1` but not at `max_depth=0`. No network, no
  torch, deterministic.
- **Format:** the markdown rendering of a `Document` list.

## Deps

`rag/requirements.txt`: `langchain-graph-retriever` (**new — not currently installed**; pulls
`graph-retriever` + `langchain-core`, the latter already present), `langgraph`,
`sentence-transformers`. Config via env: `IDEAL_RAG_MODEL`, `IDEAL_CLIENT` (path to `ideal.py`).

## Confirmed choices

1. **Read-side only**, additive; server untouched. ✅
2. **Embedder** = sentence-transformers MiniLM. ✅
3. **Output** = retrieve-only (ranked ideas + neighborhood; no LLM/key). ✅
4. **Engine** = first-party `langchain-graph-retriever` `GraphRetriever`, not hand-rolled. ✅

## One open item to confirm before building

Installing `langchain-graph-retriever` into the workspace (single new pip dependency). Everything
else follows the official pattern above.
