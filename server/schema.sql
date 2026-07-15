-- IdeaL store schema. Applied idempotently at startup.
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS ideas (
    id          TEXT PRIMARY KEY,          -- stable slug, e.g. "graph-of-atomic-ideas-3"
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,             -- the atomic idea (markdown)
    author      TEXT,                      -- who wrote it (nullable for now)
    tags        TEXT NOT NULL DEFAULT '',  -- comma-separated, normalized
    task        TEXT,                      -- task/project this idea serves (nullable)
    usefulness  INTEGER,                   -- 0..100 score, or NULL (set later)
    reputation  INTEGER,                   -- idea/author reputation score, or NULL (set later)
    status      TEXT,                      -- optional lifecycle (draft/active/archived), or NULL
    meta        TEXT,                      -- JSON blob for arbitrary future metadata, or NULL
    created_at  TEXT NOT NULL,             -- ISO-8601 UTC
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS links (
    source_id   TEXT NOT NULL REFERENCES ideas(id) ON DELETE CASCADE,
    target_id   TEXT NOT NULL REFERENCES ideas(id) ON DELETE CASCADE,
    type        TEXT NOT NULL CHECK (type IN ('similar','connected')),
    note        TEXT NOT NULL DEFAULT '',  -- short reason Claude writes for the edge
    created_at  TEXT NOT NULL,
    PRIMARY KEY (source_id, target_id, type),
    CHECK (source_id <> target_id)
);

CREATE INDEX IF NOT EXISTS idx_links_source ON links(source_id);
CREATE INDEX IF NOT EXISTS idx_links_target ON links(target_id);
