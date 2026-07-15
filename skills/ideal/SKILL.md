---
name: ideal
description: >-
  Use for the IdeaL co-vibecode idea store. Triggers on adding/capturing ideas
  ("add an idea", "save this to IdeaL", "capture this thought", "brain-dump",
  "store these notes") and on reading/querying it ("read the idea store",
  "browse IdeaL", "what has <author> been thinking about <topic>", "show idea
  <id>", "what's stored about <X>"). On ADD, split a brain-dump into atomic
  ideas, read the WHOLE store, and decide similar/connected links by reasoning —
  never by any keyword or similarity algorithm. Claude is the search engine.
---

# IdeaL — atomic idea store where you are the search engine

IdeaL is a shared store of **atomic ideas** on a cloud VM. There is **no embedding,
RAG, keyword scoring, or similarity algorithm anywhere** — not on the server, not in
this skill. The server is a dumb SQLite store plus a markdown exporter. To find what
is related, you fetch the **entire store as one markdown document** and **read it**.
Your judgment is the only search engine.

The helper CLI centralizes auth, config, and JSON. Always call it via its plugin path:

```
python3 "$CLAUDE_PLUGIN_ROOT/skills/ideal/scripts/ideal.py" <command>
```

Set `IDEAL` to that path once per session for brevity:
`IDEAL="$CLAUDE_PLUGIN_ROOT/skills/ideal/scripts/ideal.py"` then `python3 "$IDEAL" health`.

If any command reports no URL/token, tell the user to run `/ideal-setup` first — do
not guess a URL or invent a token.

---

## Flow A — ADD (writes)

Follow these steps in order.

**1. Split the brain-dump into atomic ideas.**
Atomic = one claim, concept, or question that stands on its own. Split on
"and"/"but"/"also" and topic shifts. Do **not** over-split: a claim plus the essential
rationale that makes it make sense is **one** idea. Each atomic idea gets:
- a short `title` (a handful of words),
- a `body` of 1–4 sentences,
- 0–4 lowercase `tags`.
Leave metadata (`author`, `task`, `usefulness`, `reputation`, `status`, `meta`) null
unless the user supplies it — `author` is filled from config automatically.
If the split is large (>~6 ideas) or ambiguous, show the user the proposed split and
confirm before writing.

**2. Read the whole store.**
```
python3 "$IDEAL" export
```
Read **every** idea and its links, top to bottom. Do not grep, do not skim for
keywords — the whole point is that you reason over the full document. If the store is
empty, skip dedup/linking and just add the ideas.

**3. Dedup check.**
If a new idea is essentially an existing idea's claim, do not blindly duplicate it.
Tell the user which existing idea it overlaps (by id + title) and offer:
(a) skip it, (b) add it with a single `similar` link to the existing one, or
(c) add anyway as distinct. Let the user choose.

**4. Decide edges** (see Linking guidance below).
For each new idea, produce a list of `{target_id, type, note}` against ideas that
already exist in the export. It is correct to produce **zero** edges.

**5. Write, earliest idea first.**
Add ideas one at a time so later ideas can link to the ids returned by earlier ones.
Pipe each idea as JSON on stdin:
```
echo '{"title":"...","body":"...","tags":["..."],
       "edges":[{"target_id":"existing-id","type":"connected","note":"builds on X"}]}' \
  | python3 "$IDEAL" add
```
`add` prints only the new id. If a new idea links to another new idea from the same
brain-dump, add the target first and use the id it returns.
By default an unknown `target_id` rejects the whole add (the idea is **not** created) —
that is intentional, so you never believe a nonexistent link exists. Only pass
`--on-unknown-target ignore` if the user explicitly wants the idea saved without that edge.

**6. Report.**
List each new id and its edges as `→ #<id> (similar|connected): <note>`, plus any
ideas skipped as duplicates.

---

## Flow B — READ (no writes, ever)

For questions about what is stored, **never POST**. Use:
- `python3 "$IDEAL" export` — whole-store questions (summarize, cluster, "what's stored
  about X", "what has <author> explored"). Read it and answer in prose, citing ids.
- `python3 "$IDEAL" list` — a quick id/title/tags index.
- `python3 "$IDEAL" get <id>` — one idea with its incoming and outgoing links.

Answer directly: summarize or cluster themes, do topic+author lookups by reading, or
surface an idea together with what it links to. Reading writes nothing — do not call
`add` or `/links` in this flow.

---

## Linking guidance (the heart of the skill)

- **`similar`** = the two ideas are *about the same thing* — mergeable, near-duplicate,
  or one subsumes the other.
- **`connected`** = *distinct* ideas that relate — builds-on, motivates, is-an-example-of,
  contrasts, or is a counterargument. Put the specific relationship in the `note`.
- **When unsure between the two, use `connected`.**
- **0–4 edges per idea; 1–2 is typical.** Create **none** rather than invent weak links.
  "Both mention databases" is *not* a link. Only link ideas whose relationship you could
  defend in one sentence.
- **No self-links. No duplicate edges** (a given source→target→type is idempotent; the
  server ignores repeats).
- **Every edge needs a `note`** of ≤ ~12 words stating the *relationship*, not a summary
  of the target ("builds on: edges carry context", not "about graphs").

Edges are directed and outgoing from the new idea; the server does not create reverse
edges. If you believe a relationship should also point back, that is your reasoning to
apply when reading — do not fabricate a second edge unless the user wants it recorded.
