"""SQLite access: connection setup, schema init, and small typed helpers.

All SQL lives here and uses parameterized queries. Connections run in autocommit
mode (isolation_level=None) so write paths manage transactions explicitly with
BEGIN IMMEDIATE / COMMIT / ROLLBACK.
"""
import os
import sqlite3
from datetime import datetime, timezone

import config

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.settings.db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None  # autocommit; transactions managed manually
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


# Columns added after v1 shipped. `schema.sql` includes them for fresh DBs; an
# existing store (e.g. the live VM) gets them via idempotent ALTER TABLE below.
_MIGRATIONS = (
    ("ideas", "embedding", "BLOB"),
    ("ideas", "embedding_model", "TEXT"),
    ("ideas", "embedding_dim", "INTEGER"),
)


def init_schema() -> None:
    directory = os.path.dirname(config.settings.db_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = connect()
    try:
        with open(_SCHEMA_PATH, "r", encoding="utf-8") as fh:
            conn.executescript(fh.read())
        _apply_migrations(conn)
    finally:
        conn.close()


def _apply_migrations(conn) -> None:
    for table, column, decl in _MIGRATIONS:
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


# --- reads -------------------------------------------------------------------

def idea_exists(conn, idea_id: str) -> bool:
    return conn.execute("SELECT 1 FROM ideas WHERE id = ?", (idea_id,)).fetchone() is not None


def fetch_idea(conn, idea_id: str):
    return conn.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()


def fetch_all_ideas(conn):
    return conn.execute("SELECT * FROM ideas ORDER BY created_at ASC, id ASC").fetchall()


def list_ideas(conn):
    return conn.execute(
        "SELECT id, title, tags, author, usefulness, reputation, status, updated_at "
        "FROM ideas ORDER BY created_at ASC, id ASC"
    ).fetchall()


def fetch_all_links(conn):
    return conn.execute(
        "SELECT source_id, target_id, type, note FROM links "
        "ORDER BY source_id ASC, type ASC, target_id ASC"
    ).fetchall()


def fetch_links_out(conn, idea_id: str):
    return conn.execute(
        "SELECT target_id, type, note FROM links WHERE source_id = ? "
        "ORDER BY type ASC, target_id ASC",
        (idea_id,),
    ).fetchall()


def fetch_links_in(conn, idea_id: str):
    return conn.execute(
        "SELECT source_id, type, note FROM links WHERE target_id = ? "
        "ORDER BY type ASC, source_id ASC",
        (idea_id,),
    ).fetchall()


def counts(conn):
    ideas = conn.execute("SELECT COUNT(*) AS c FROM ideas").fetchone()["c"]
    links = conn.execute("SELECT COUNT(*) AS c FROM links").fetchone()["c"]
    return ideas, links


# --- embeddings (server-side RAG index) --------------------------------------

def fetch_persisted_embeddings(conn):
    """Every idea that already has a stored vector — used to warm the in-memory
    index at startup without loading the model."""
    return conn.execute(
        "SELECT id, embedding, embedding_model, embedding_dim FROM ideas "
        "WHERE embedding IS NOT NULL"
    ).fetchall()


def fetch_unembedded(conn, model: str):
    """Ideas with no vector, or one from a different model — need (re)embedding."""
    return conn.execute(
        "SELECT id, title, body FROM ideas "
        "WHERE embedding IS NULL OR embedding_model IS NOT ? "
        "ORDER BY created_at ASC, id ASC",
        (model,),
    ).fetchall()


# --- writes ------------------------------------------------------------------

def insert_idea(conn, idea_id: str, fields: dict, when: str) -> None:
    conn.execute(
        """
        INSERT INTO ideas
            (id, title, body, author, tags, task, usefulness, reputation,
             status, meta, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            idea_id,
            fields["title"],
            fields["body"],
            fields.get("author"),
            fields.get("tags", ""),
            fields.get("task"),
            fields.get("usefulness"),
            fields.get("reputation"),
            fields.get("status"),
            fields.get("meta"),
            when,
            when,
        ),
    )


def set_embedding(conn, idea_id: str, blob: bytes, model: str, dim: int) -> None:
    """Persist one idea's vector (raw float32 bytes) and the model that made it."""
    conn.execute(
        "UPDATE ideas SET embedding = ?, embedding_model = ?, embedding_dim = ? WHERE id = ?",
        (blob, model, dim, idea_id),
    )


def insert_link(conn, source_id: str, target_id: str, type_: str, note: str, when: str) -> bool:
    """Insert an edge idempotently. Returns True if a new row was created."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO links (source_id, target_id, type, note, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (source_id, target_id, type_, note, when),
    )
    return cur.rowcount > 0


# Columns an update is allowed to touch. Fixed whitelist — never user-supplied,
# so it is safe to interpolate into the SET clause.
UPDATABLE_COLUMNS = (
    "title", "body", "author", "tags", "task",
    "usefulness", "reputation", "status", "meta",
)


def update_idea(conn, idea_id: str, fields: dict, when: str) -> bool:
    """Update the given columns of one idea and bump updated_at. `fields` keys
    must be drawn from UPDATABLE_COLUMNS. Returns True if the idea existed."""
    cols = [c for c in fields if c in UPDATABLE_COLUMNS]
    assignments = [f"{c} = ?" for c in cols] + ["updated_at = ?"]
    params = [fields[c] for c in cols] + [when]
    # Invalidate the cached embedding when the embedded text (title/body) changes,
    # so a failed re-embed leaves NULL (backfilled later) rather than a stale vector.
    if "title" in cols or "body" in cols:
        assignments += ["embedding = NULL", "embedding_model = NULL", "embedding_dim = NULL"]
    params.append(idea_id)
    cur = conn.execute(
        f"UPDATE ideas SET {', '.join(assignments)} WHERE id = ?", params
    )
    return cur.rowcount > 0


def delete_idea(conn, idea_id: str) -> bool:
    """Delete one idea. Its links cascade (ON DELETE CASCADE + foreign_keys=ON).
    Returns True if a row was removed."""
    cur = conn.execute("DELETE FROM ideas WHERE id = ?", (idea_id,))
    return cur.rowcount > 0


def delete_link(conn, source_id: str, target_id: str, type_: str) -> bool:
    """Delete one specific edge. Returns True if a row was removed."""
    cur = conn.execute(
        "DELETE FROM links WHERE source_id = ? AND target_id = ? AND type = ?",
        (source_id, target_id, type_),
    )
    return cur.rowcount > 0
