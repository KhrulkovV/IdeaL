"""Optional server-side semantic search — the ONE place the server is not 'dumb'.

The core add/link flow stays reasoning-driven: Claude decides which ideas are
`similar`/`connected`, and the server only stores those edges. This is an
*additive, read-side* layer. It embeds each idea's text once at write time,
persists the vector next to the idea (a BLOB column), keeps the vectors warm in
an in-memory index, and answers `POST /search` by seeding on vector similarity
then traversing the links Claude already authored. It never invents links.

The real embedder (sentence-transformers) is imported lazily, so importing this
module — and running the whole server test suite — needs no torch. Tests inject a
fake embedder via `set_embedder()`.
"""
from __future__ import annotations

import json
import logging
import threading
from collections import deque
from typing import Dict, List, Optional, Tuple

import numpy as np

import db
import ids

logger = logging.getLogger("ideal.rag")

DEFAULT_MODEL = "Snowflake/snowflake-arctic-embed-s"


def _text(title: str, body: str) -> str:
    return f"{title}\n\n{body}".strip()


class SentenceTransformerEmbedder:
    """sentence-transformers wrapper. Encodes to L2-normalized float32 vectors so
    cosine similarity is a plain dot product. Constructing it loads the model.

    Asymmetric models (e.g. arctic-embed) sharpen retrieval by prefixing the query
    side with a `query` prompt while embedding documents bare; `is_query=True`
    applies that prompt when the loaded model declares one. Symmetric models (e.g.
    MiniLM) declare no `query` prompt, so the flag is a no-op for them."""

    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer  # lazy: torch only here

        self.model_name = model_name
        self._model = SentenceTransformer(model_name)
        self.dim = int(self._model.get_sentence_embedding_dimension())

    def encode(self, texts: List[str], is_query: bool = False) -> np.ndarray:
        kwargs = dict(
            normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False
        )
        if is_query and "query" in (self._model.prompts or {}):
            kwargs["prompt_name"] = "query"
        vecs = self._model.encode(list(texts), **kwargs)
        return np.asarray(vecs, dtype=np.float32)


class RagEngine:
    """Holds the in-memory {idea_id: vector} index, backed by persisted BLOBs."""

    def __init__(self, model_name: str = DEFAULT_MODEL, enabled: bool = True):
        self.model_name = model_name
        self.enabled = enabled
        self._embedder = None                    # SentenceTransformerEmbedder or injected fake
        self._dim: Optional[int] = None
        self._vecs: Dict[str, np.ndarray] = {}   # idea_id -> normalized float32 (dim,)
        self._lock = threading.Lock()            # guards _vecs + serializes re-index

    # -- embedder management --------------------------------------------------

    def set_embedder(self, embedder) -> None:
        """Inject an embedder (tests pass a fake so the real model never loads)."""
        self._embedder = embedder
        self._dim = int(embedder.dim)

    def _get_embedder(self):
        if self._embedder is None:
            self._embedder = SentenceTransformerEmbedder(self.model_name)
            self._dim = self._embedder.dim
        return self._embedder

    @property
    def dim(self) -> Optional[int]:
        return self._dim

    def _encode_one(self, title: str, body: str) -> np.ndarray:
        return self._get_embedder().encode([_text(title, body)])[0].astype(np.float32)

    # -- index lifecycle ------------------------------------------------------

    def load_persisted(self, conn) -> int:
        """Warm the index from stored vectors matching the current model. No model
        load required — this is cheap even for the whole store."""
        self._vecs.clear()
        loaded = 0
        for row in db.fetch_persisted_embeddings(conn):
            if row["embedding_model"] != self.model_name:
                continue
            vec = np.frombuffer(row["embedding"], dtype=np.float32)
            stored_dim = row["embedding_dim"]
            if stored_dim is not None and vec.shape[0] != stored_dim:
                logger.warning(
                    "skipping idea %s: embedding bytes imply dim %d but row records %d",
                    row["id"], vec.shape[0], stored_dim,
                )
                continue
            if self._dim is not None and vec.shape[0] != self._dim:
                continue
            self._vecs[row["id"]] = vec
            if self._dim is None:
                self._dim = int(vec.shape[0])
            loaded += 1
        return loaded

    def backfill(self, conn) -> int:
        """Embed + persist every idea lacking a current-model vector and add it to
        the index. One-time for a pre-existing store; loads the model if needed."""
        rows = db.fetch_unembedded(conn, self.model_name)
        if not rows:
            return 0
        texts = [_text(r["title"], r["body"]) for r in rows]
        matrix = self._get_embedder().encode(texts)
        for row, vec in zip(rows, matrix):
            vec = np.asarray(vec, dtype=np.float32)
            db.set_embedding(conn, row["id"], vec.tobytes(), self.model_name, int(vec.shape[0]))
            self._vecs[row["id"]] = vec
        return len(rows)

    # -- write-path hooks (called after the core transaction commits) ---------

    def index_idea(self, idea_id: str) -> None:
        """(Re)embed one idea from its CURRENT committed DB text, persist the vector,
        and publish it to the index. Re-reading under the lock means a slow re-embed
        that lands after a newer concurrent update still writes the newest committed
        text's vector — the index can't drift out of sync with the row. Best-effort:
        never raises into the write path, and never leaves a text-mismatched vector."""
        if not self.enabled:
            return
        with self._lock:
            try:
                conn = db.connect()
                try:
                    row = db.fetch_idea(conn, idea_id)
                    if row is None:  # deleted between commit and index — nothing to embed
                        self._vecs.pop(idea_id, None)
                        return
                    vec = self._encode_one(row["title"], row["body"])
                    db.set_embedding(
                        conn, idea_id, vec.tobytes(), self.model_name, int(vec.shape[0])
                    )
                finally:
                    conn.close()
                self._vecs[idea_id] = vec
            except Exception as exc:  # noqa: BLE001 — the store write already succeeded
                self._vecs.pop(idea_id, None)  # drop rather than serve stale text
                logger.warning("failed to index idea %s: %s", idea_id, exc)

    def remove(self, idea_id: str) -> None:
        with self._lock:
            self._vecs.pop(idea_id, None)

    # -- retrieval ------------------------------------------------------------

    def search(self, conn, query: str, k: int = 8, start_k: int = 4, hops: int = 1) -> dict:
        """Vector-seed then traverse links. Returns {query, results, context}."""
        with self._lock:  # snapshot so a concurrent remove/index can't mutate mid-read
            items = list(self._vecs.items())
        if not items:
            return {"query": query, "results": [], "context": ""}

        qvec = self._get_embedder().encode([query], is_query=True)[0].astype(np.float32)
        ids_list = [idea_id for idea_id, _ in items]
        matrix = np.stack([vec for _, vec in items])           # (N, dim)
        sims = matrix @ qvec                                   # cosine (all normalized)

        order = np.argsort(-sims)[: max(1, start_k)]
        seeds: List[Tuple[str, float]] = [(ids_list[i], float(sims[i])) for i in order]

        chosen: Dict[str, dict] = {}
        for idea_id, score in seeds:
            chosen[idea_id] = {"depth": 0, "score": score, "reason": "vector seed"}

        # Breadth-first over the links (undirected), out to `hops`, capped at `k`.
        if hops > 0 and len(chosen) < k:
            adjacency = _build_adjacency(conn)
            frontier = deque((sid, 0) for sid, _ in seeds)
            while frontier and len(chosen) < k:
                node, depth = frontier.popleft()
                if depth >= hops:
                    continue
                for nbr, etype in adjacency.get(node, ()):  # noqa: B007
                    if nbr in chosen:
                        continue
                    chosen[nbr] = {
                        "depth": depth + 1,
                        "score": None,
                        "reason": f"{depth + 1} hop via {etype} from {node}",
                    }
                    frontier.append((nbr, depth + 1))
                    if len(chosen) >= k:
                        break

        ordered = sorted(chosen.items(), key=_sort_key)[:k]

        rows = {}
        for idea_id, _ in ordered:
            row = db.fetch_idea(conn, idea_id)
            if row is not None:
                rows[idea_id] = row

        results = []
        for idea_id, info in ordered:
            row = rows.get(idea_id)
            if row is None:  # index entry for a since-deleted idea; skip
                continue
            results.append({
                "id": idea_id,
                "title": row["title"],
                "depth": info["depth"],
                "score": info["score"],
                "reason": info["reason"],
                "tags": ids.split_tags(row["tags"]),
            })
        return {"query": query, "results": results, "context": _render(ordered, rows)}


def _sort_key(item):
    _id, info = item
    if info["depth"] == 0:
        return (0, -(info["score"] or 0.0), _id)
    return (1, info["depth"], _id)


def _build_adjacency(conn) -> Dict[str, List[Tuple[str, str]]]:
    """Undirected adjacency {idea_id: [(neighbour_id, edge_type), ...]} from all
    links — a `[[target-id]]` edge is followed in both directions."""
    adj: Dict[str, List[Tuple[str, str]]] = {}
    for row in db.fetch_all_links(conn):
        s, t, ty = row["source_id"], row["target_id"], row["type"]
        adj.setdefault(s, []).append((t, ty))
        adj.setdefault(t, []).append((s, ty))
    return adj


def _source_line(meta_json) -> str:
    """Best-effort one-line provenance from the idea's `meta` JSON, if any."""
    if not meta_json:
        return ""
    try:
        meta = json.loads(meta_json)
    except (TypeError, ValueError):
        return ""
    if not isinstance(meta, dict):
        return ""
    src = meta.get("source") or meta.get("paper")
    if isinstance(src, str) and src.strip():
        return "source: " + src.strip()
    if isinstance(src, dict):
        title = src.get("title")
        if isinstance(title, str) and title.strip():
            return "source: " + title.strip()
    return ""


def _render(ordered, rows) -> str:
    """Markdown block of the retrieved ideas — feed to any reader/LLM, or just read.
    Each idea is tagged as a vector seed (with score) or the hop it was reached at."""
    blocks = []
    for idea_id, info in ordered:
        row = rows.get(idea_id)
        if row is None:
            continue
        if info["depth"] == 0:
            tag = f"seed · score {info['score']:.3f}" if info["score"] is not None else "seed"
        else:
            tag = f"reached · {info['depth']} hop out"
        lines = [f"## {row['title']}", f"`{idea_id}` · {tag}"]
        meta_bits = []
        tags = ids.split_tags(row["tags"])
        if tags:
            meta_bits.append("tags: " + ", ".join(tags))
        src = _source_line(row["meta"])
        if src:
            meta_bits.append(src)
        if meta_bits:
            lines.append(" · ".join(meta_bits))
        body = (row["body"] or "").strip()
        if body:
            lines.append("")
            lines.append(body)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
