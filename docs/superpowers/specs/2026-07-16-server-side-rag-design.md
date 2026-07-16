# IdeaL — server-side GraphRAG (persistent, embed-on-write)

## Why this exists / what it changes

The read-side GraphRAG first shipped **client-side** (the `rag/` package): every query pulled the
whole store and re-embedded all ideas locally. That wastes work and needs the ML stack on every
reader. This moves the semantic engine **onto the VM**: embeddings are computed once at write time,
persisted next to each idea, held warm in memory, and a `POST /search` endpoint does the whole
retrieval server-side. Readers become thin HTTP callers with **no ML dependency**.

**Deliberate constraint change.** IdeaL's core premise — the server is a dumb store, all
similarity/linking is Claude's reasoning — still holds for the ADD/link flow. This adds **one**
exception: an *additive, read-side* semantic index. The core `POST /ideas` reasoning (Claude decides
`similar`/`connected`) is untouched; the server never invents links. It only embeds text for
retrieval and traverses the links Claude already authored.

## Data model additions (migration on existing DB)

Three nullable columns on `ideas`, added idempotently at startup (fresh DB gets them in
`schema.sql`; the live 129-idea DB gets them via `ALTER TABLE ADD COLUMN` in `init_schema`):

| column | meaning |
|---|---|
| `embedding BLOB` | float32 vector bytes (L2-normalized), or NULL if not yet embedded |
| `embedding_model TEXT` | model name that produced it (invalidate on model change) |
| `embedding_dim INTEGER` | vector length (sanity check on load) |

Staleness is driven by NULL: updating `title`/`body` sets `embedding = NULL`, so the idea is
re-embedded on next write-index or startup backfill. No content-hash column needed.

## Components

- **`server/rag_engine.py`** — the engine, isolated so it can be tested with a fake embedder (no
  torch). Holds an in-memory `{id: np.float32 vector}` map backed by the persisted BLOBs.
  - `RagEngine(model_name, enabled)`; lazy real embedder (imports `sentence_transformers` only on
    first use). `set_embedder(fake)` for tests.
  - `load_persisted(conn)` — fill memory from stored vectors matching the current model (startup).
  - `backfill(conn)` — embed + persist any ideas with NULL/mismatched embedding (the existing 129,
    one-time; later restarts find none).
  - `index_idea(idea_id, title, body)` — embed one idea, persist the BLOB, update memory
    (called after create, and after an update that changed title/body).
  - `remove(idea_id)` — drop from memory (after delete; the row/BLOB is already gone).
  - `search(conn, query, k, start_k, hops)` — embed query → cosine top-`start_k` seeds over the
    in-memory matrix → BFS the links (both directions, from `db.fetch_all_links`) out `hops`, capped
    at `k` → `{query, results:[{id,title,depth,score,reason,via}], context}` with a markdown block.

- **`server/config.py`** — `rag_enabled` (`IDEAL_RAG_ENABLED`, default true) and `rag_model`
  (`IDEAL_RAG_MODEL`, default `all-MiniLM-L6-v2`).

- **`server/db.py`** — `set_embedding`, `clear_embedding`, `fetch_persisted_embeddings`,
  `fetch_unembedded`; `update_idea` clears the embedding when title/body change.

- **`server/models.py`** — `SearchRequest{query,k=8,start_k=4,hops=1}`, `SearchHit`,
  `SearchResponse`.

- **`server/app.py`** — build the engine at import (`rag = RagEngine(...)`); `lifespan` runs
  `load_persisted` + `backfill`. `POST /search` (auth = read) returns the ranked slice; 503 when
  `rag_enabled` is false. `create`/`update`/`delete` call the engine after their transaction commits
  so indexing never blocks or breaks the core write path.

## Client

- **`skills/ideal/scripts/ideal.py`** gains a stdlib `search "<query>" [--k --start-k --hops --json]`
  command → `POST /search`. Readers need only Python stdlib — the whole point of moving the engine
  server-side.
- **`commands/ideal-search.md`** repoints to `ideal.py search`.
- The old client-side **`rag/`** package was **removed** once the server endpoint became the only
  retrieval path — no consumer imported it, so it was dead weight. See the superseded design in
  `2026-07-16-graphrag-retrieval-design.md`.

## Deploy

Docker image gains `sentence-transformers` + `numpy` (CPU torch, ~1–2 GB image, few-hundred-MB RAM
for the warm model). Redeploy on the VM: `git pull && ./scripts/deploy.sh` (rebuild). First boot
backfills the 129 existing ideas (a few seconds), then the model stays warm. `IDEAL_RAG_ENABLED=false`
skips all of it for a lightweight deploy.

## Testing (no torch)

A `FakeEmbedder` (bag-of-words over a fixed vocab, `dim`, `encode()->float32`) is injected via
`rag.set_embedder(...)` in `conftest`, so the real model never loads in tests. Behaviour tested
through the API: embed-on-write populates the index; `POST /search` seeds by vector match; a linked
idea whose text doesn't match is pulled in at `hops=1` but not `hops=0`; traversal is undirected;
updating a body re-embeds; `IDEAL_RAG_ENABLED=false` → 503. Existing server tests stay green
(new columns are nullable, engine calls are no-ops when the index is empty).
