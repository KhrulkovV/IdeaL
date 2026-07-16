# rag — GraphRAG retrieval over IdeaL (additive, read-only)

Optional semantic retrieval layer. It **does not** change how ideas are written or linked — the
core still exports the whole store as markdown for Claude to reason over. This is just a way to pull
a relevant *sub-slice* by query instead of dumping everything into context.

## How it works

Engine is LangChain's first-party [`langchain-graph-retriever`](https://docs.langchain.com/oss/python/integrations/retrievers/graph_rag)
(`GraphRetriever`) — basic GraphRAG, nothing hand-rolled:

1. **Seed** — embed each idea (`title` + `body`) with sentence-transformers MiniLM into an
   in-memory vector store; take the top `--start-k` by cosine to the query.
2. **Traverse** — walk out `--hops` along the `[[target-id]]` wikilinks (`connected` and `similar`,
   both directions) to pull in each seed's neighbourhood — including ideas whose own text didn't
   match, because the edges are Claude-reasoned.
3. **Format** — a thin LangGraph `StateGraph` (`retrieve → format`, no LLM) renders a ranked
   markdown block, each idea tagged seed/score or the hop it was reached at, with paper provenance.

## Use

```bash
pip install -r rag/requirements.txt

python -m rag.search "coarse space construction for algebraic multigrid"
python -m rag.search "feature engineering for tree models" --start-k 3 --hops 1
python -m rag.search "..." --json      # machine-readable {query, results, context}
```

Fetches the store through the existing `skills/ideal/scripts/ideal.py` client (reuses its
config/auth). Env: `IDEAL_RAG_MODEL` (embedder, default `all-MiniLM-L6-v2`), `IDEAL_CLIENT`
(path to `ideal.py`).

## Test

```bash
python -m pytest rag/tests/ -q     # 12 tests, no torch/network (fake Embeddings)
```

Design: `docs/superpowers/specs/2026-07-16-graphrag-retrieval-design.md`.
