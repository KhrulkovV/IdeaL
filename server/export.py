"""Pure rendering of the store into the plain-markdown document Claude reads,
and a structured JSON dump. No database or HTTP here — trivially unit-testable.
"""
import json

from ids import split_tags

_DASH = "—"  # em dash, shown for null/empty metadata fields

_LEGEND = (
    "similar (near-duplicate/overlap), connected (relates/builds-on/contrasts)"
)
_NOTE = (
    "Each idea lists only OUTGOING links; every edge appears exactly once, under "
    "its source. IDs in `code` are stable — reference them as target_id."
)


def _or_dash(value):
    if value is None or value == "":
        return _DASH
    return str(value)


def _tags_str(stored_tags: str) -> str:
    tags = split_tags(stored_tags)
    return ", ".join(tags) if tags else _DASH


def _date_only(iso: str) -> str:
    return (iso or "").split("T", 1)[0] or _DASH


def _meta_line(idea) -> str:
    return (
        f"`{idea['id']}` · {_or_dash(idea['author'])} · "
        f"tags: {_tags_str(idea['tags'])} · "
        f"status: {_or_dash(idea['status'])} · "
        f"task: {_or_dash(idea['task'])} · "
        f"usefulness: {_or_dash(idea['usefulness'])} · "
        f"reputation: {_or_dash(idea['reputation'])} · "
        f"updated {_date_only(idea['updated_at'])}"
    )


def render_markdown(ideas, links, generated_at: str) -> str:
    """Render every idea + its outgoing links as one markdown document.

    `ideas`: iterable of idea rows (mapping access by column name).
    `links`: iterable of link rows with source_id, target_id, type, note.
    """
    links_by_source = {}
    link_count = 0
    for link in links:
        links_by_source.setdefault(link["source_id"], []).append(link)
        link_count += 1

    ideas = list(ideas)
    lines = [
        "---",
        "store: IdeaL",
        f"generated_at: {generated_at}",
        f"idea_count: {len(ideas)}",
        f"link_count: {link_count}",
        f"link_types: {_LEGEND}",
        f"note: {_NOTE}",
        "---",
        "",
    ]

    for idea in ideas:
        lines.append(f"## {idea['title']}")
        lines.append(_meta_line(idea))
        lines.append("")
        lines.append(idea["body"])
        lines.append("")
        lines.append("Links:")
        out = links_by_source.get(idea["id"], [])
        if out:
            for link in out:
                note = link["note"] or ""
                suffix = f" — {note}" if note else ""
                lines.append(
                    f"- **{link['type']}** → [[{link['target_id']}]]{suffix}"
                )
        else:
            lines.append("- _(no outgoing links)_")
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_json(ideas, links, generated_at: str) -> str:
    """Structured full dump (debugging / backup convenience)."""
    links_by_source = {}
    for link in links:
        links_by_source.setdefault(link["source_id"], []).append(
            {"target_id": link["target_id"], "type": link["type"], "note": link["note"]}
        )

    payload = {
        "store": "IdeaL",
        "generated_at": generated_at,
        "ideas": [
            {
                "id": idea["id"],
                "title": idea["title"],
                "body": idea["body"],
                "author": idea["author"],
                "tags": split_tags(idea["tags"]),
                "task": idea["task"],
                "usefulness": idea["usefulness"],
                "reputation": idea["reputation"],
                "status": idea["status"],
                "meta": json.loads(idea["meta"]) if idea["meta"] else None,
                "created_at": idea["created_at"],
                "updated_at": idea["updated_at"],
                "links_out": links_by_source.get(idea["id"], []),
            }
            for idea in ideas
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)
