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

## Integrate (use it without Claude)

The package is plain Python — no Claude, no LLM anywhere in the retrieve path. Three entry points:

**1. CLI → JSON** (shell out from anything):

```bash
python -m rag.search "your query" --json      # -> {"query", "results":[{id,title,depth,score}], "context"}
```

**2. Python — `search()`** for the ranked slice + ready-made markdown block:

```python
from rag.search import load_documents, search
from rag.embedder import MiniLMEmbeddings

emb = MiniLMEmbeddings()                 # loads MiniLM once; reuse across queries
docs = load_documents()                  # pulls the store via ideal.py (or pass your own, below)
res = search("ssh tunnel to a firewalled service", documents=docs, embeddings=emb,
             k=6, start_k=3, hops=1)
res["results"]     # [{id, title, depth (0=seed), score}, ...]
res["context"]     # markdown block of the retrieved ideas — feed to any LLM, or just read
```

**3. Python — the raw LangChain retriever** to drop into your own LangChain/LangGraph pipeline:

```python
from rag.search import build_retriever
retriever = build_retriever(docs, emb, k=6, start_k=3, max_depth=1)  # a real LC BaseRetriever
retriever.invoke("your query")           # -> List[langchain_core.documents.Document]
#   each doc's .metadata has _depth (0=vector seed, >=1=reached via wikilink) and _similarity_score
```

**Bring your own data** (skip `ideal.py` entirely) — anything shaped like the export works:

```python
from rag.store import to_documents
docs = to_documents({"ideas": [
    {"id": "a", "title": "A", "body": "...", "links_out": [{"target_id": "b", "type": "similar"}]},
    {"id": "b", "title": "B", "body": "..."},
]})
```

**Feed it to any model** — `res["context"]` is just a string:

```python
prompt = f"Answer using only these notes:\n\n{res['context']}\n\nQ: {question}"
# hand `prompt` to OpenAI, a local model, whatever — the GraphRAG part is already done
```

Point at a different embedder via `IDEAL_RAG_MODEL`, or a different client via `IDEAL_CLIENT`.

## Test

```bash
python -m pytest rag/tests/ -q     # 12 tests, no torch/network (fake Embeddings)
```

Design: `docs/superpowers/specs/2026-07-16-graphrag-retrieval-design.md`.
