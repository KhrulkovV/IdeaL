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


def init_schema() -> None:
    directory = os.path.dirname(config.settings.db_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = connect()
    try:
        with open(_SCHEMA_PATH, "r", encoding="utf-8") as fh:
            conn.executescript(fh.read())
    finally:
        conn.close()


# --- reads -------------------------------------------------------------------

def idea_exists(conn, idea_id: str) -> bool:
    return conn.execute("SELECT 1 FROM ideas WHERE id = ?", (idea_id,)).fetchone() is not None


def fetch_idea(conn, idea_id: str):
    return conn.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()


def fetch_all_ideas(conn):
    return conn.execute("SELECT * FROM ideas ORDER BY created_at ASC, id ASC").fetchall()


def list_ideas(conn):
    return conn.execute(
        "SELECT id, title, tags, updated_at FROM ideas ORDER BY created_at ASC, id ASC"
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


def insert_link(conn, source_id: str, target_id: str, type_: str, note: str, when: str) -> bool:
    """Insert an edge idempotently. Returns True if a new row was created."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO links (source_id, target_id, type, note, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (source_id, target_id, type_, note, when),
    )
    return cur.rowcount > 0
