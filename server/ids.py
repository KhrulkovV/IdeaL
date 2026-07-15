"""Human-readable, collision-free idea IDs (slugs) and tag normalization."""
import re

_MAX_SLUG_LEN = 60


def slugify(title: str) -> str:
    """Lowercase, collapse non-alphanumerics to single dashes, trim to length.

    Falls back to "idea" when the title has no usable characters.
    """
    s = title.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    if len(s) > _MAX_SLUG_LEN:
        s = s[:_MAX_SLUG_LEN].rstrip("-")
    return s or "idea"


def unique_id(conn, title: str) -> str:
    """Return a slug for `title` unique within the ideas table.

    The bare slug is used when free; otherwise "-2", "-3", ... is appended.
    """
    base = slugify(title)
    if conn.execute("SELECT 1 FROM ideas WHERE id = ?", (base,)).fetchone() is None:
        return base
    n = 2
    while True:
        candidate = f"{base}-{n}"
        if conn.execute("SELECT 1 FROM ideas WHERE id = ?", (candidate,)).fetchone() is None:
            return candidate
        n += 1


def normalize_tags(tags) -> str:
    """Normalize a list of tags into a stored comma-separated string.

    Lowercased, trimmed, de-duplicated (order-preserving), empties dropped.
    """
    if not tags:
        return ""
    seen = []
    for tag in tags:
        t = str(tag).strip().lower()
        if t and t not in seen:
            seen.append(t)
    return ",".join(seen)


def split_tags(stored: str):
    """Inverse of normalize_tags: stored string -> list."""
    if not stored:
        return []
    return [t for t in stored.split(",") if t]
