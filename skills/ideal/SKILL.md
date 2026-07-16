---
name: ideal
description: >-
  Use for the IdeaL co-vibecode idea store. Triggers on adding/capturing ideas
  ("add an idea", "save this to IdeaL", "capture this thought", "brain-dump",
  "store these notes"), on reading/querying it ("read the idea store",
  "browse IdeaL", "what has <author> been thinking about <topic>", "show idea
  <id>", "what's stored about <X>", "find/search ideas about <X>"), on
  rating/endorsing ideas ("this idea is very good", "that one's reliable/solid",
  "mark X as weak", "rate idea Y"), and on editing or removing them ("update idea
  X", "fix that idea", "delete idea Y").
  On ADD, split a brain-dump into atomic ideas, read the WHOLE store, and decide
  similar/connected links by reasoning — never by any keyword or similarity
  algorithm. An optional server-side semantic search (`ideal.py search`) can pull
  a relevant slice for reads, but Claude remains the linker.
---

# IdeaL — atomic idea store where you are the search engine

IdeaL is a shared store of **atomic ideas** on a cloud VM. **No algorithm decides how
ideas relate**: you split brain-dumps into atoms and choose every `similar`/`connected`
link by reasoning over the whole store — never by keyword or similarity score. That
write/link path is the heart of the skill and has no algorithm in it. The default way
to find what is related is still to fetch the **entire store as one markdown document**
and **read it**; your judgment is the linker.

For *retrieval only*, the server also offers an **optional** semantic search
(`ideal.py search`, see Flow B) that embeds ideas and traverses your Claude-authored
links to pull a relevant sub-slice. It is a convenience for large stores — read-only,
and never a step in writing or linking. It can be turned off entirely at deploy time
(`IDEAL_RAG_ENABLED=false`), in which case `search` reports that it is disabled.

The helper CLI centralizes auth, config, and JSON. Always call it via its plugin path:

```
python3 "$CLAUDE_PLUGIN_ROOT/skills/ideal/scripts/ideal.py" <command>
```

Set `IDEAL` to that path once per session for brevity:
`IDEAL="$CLAUDE_PLUGIN_ROOT/skills/ideal/scripts/ideal.py"` then `python3 "$IDEAL" health`.

If any command reports no URL/token, tell the user to run `/ideal:ideal-setup` first — do
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

For questions about what is stored, **never write** (no `add`, no `/links`, no
`update`/`delete`). Use:
- `python3 "$IDEAL" export` — whole-store questions (summarize, cluster, "what's stored
  about X", "what has <author> explored"). Read it and answer in prose, citing ids.
- `python3 "$IDEAL" list` — a quick id/title/tags index.
- `python3 "$IDEAL" get <id>` — one idea with its incoming and outgoing links.

Answer directly: summarize or cluster themes, do topic+author lookups by reading, or
surface an idea together with what it links to. Reading writes nothing — do not call
`add` or `/links` in this flow.

When the user asks for the "best", "most reliable", or "most useful" ideas, rank by
the `reputation` / `usefulness` values shown in the export (higher = better). Ideas
left at `—` are simply unrated, not bad — say so rather than treating them as low.

### Optional: semantic search (`search`) — still read-only

```
python3 "$IDEAL" search "coarse space construction for algebraic multigrid"
```
It embeds the query, seeds by cosine similarity, then walks your `similar`/`connected`
links out a hop to pull in related ideas — including ones whose own text didn't match,
because the edges are your reasoning. Output is a ranked list plus a ready-to-read
markdown context block. Flags: `--k` (max results), `--start-k` (vector seeds),
`--hops` (link-traversal depth), `--json` (raw `{query, results, context}`).

**When to reach for `search` vs. `export` — the whole export is the default.**

| Use `search` (a focused slice) | Dump the whole store via `export` (read it all) |
|---|---|
| The store is **large** and a full dump would blow or crowd the context window | **Deep / thorough research** — synthesis, "map everything about X", surveys |
| A quick, targeted lookup — "is there anything on <topic>?", "find the idea about Y" | **Any ADD flow** — dedup + link decisions need the *whole* store, always |
| You want to save context and a relevant sub-slice is enough | You need completeness and can afford the tokens |

When in doubt, prefer `export` — the ranked slice is a convenience that trades
completeness for context, and it can miss a relevant idea a full read would catch.

`search` is a **retrieval convenience, not a replacement for reading**:
- It is **read-only** — like everything in Flow B, it never writes, and it never
  decides links. Choosing `similar`/`connected` edges is always the ADD flow: your
  reasoning over the full `export`, never this ranking.
- If the server was deployed with `IDEAL_RAG_ENABLED=false`, `search` prints a clear
  "semantic search disabled" message; fall back to `export` / `list` / `get`.

---

## Flow C — RATE & EDIT (updates)

Two metadata scores let users express judgment about an idea; both are 0–100 and
null until set. **`reputation`** = how good / reliable / trusted the idea is (an
endorsement). **`usefulness`** = how useful it is for a task at hand. When the user
says "this idea is very good", "that one's solid/reliable", "weak", etc., set
`reputation`; when they speak to usefulness for a task, set `usefulness`.

1. **Find the idea.** If the user names an id, use it. Otherwise run `export`, read,
   and identify the idea they mean (confirm if ambiguous).
2. **Map the judgment to a 0–100 score** (if the user gives a number, use it):

   | user says | reputation |
   |---|---|
   | excellent / very good / proven / highly reliable | ~90 |
   | good / solid / reliable | ~75 |
   | okay / neutral / unsure | ~50 |
   | weak / shaky / unreliable | ~25 |
   | bad / wrong / debunked | ~10 |

   Nudge relative to any existing value rather than resetting (e.g. "even better" on
   a 75 → ~90).
3. **Write it** with a partial update — send only the fields that change:
   ```
   echo '{"reputation": 90}' | python3 "$IDEAL" update <id>
   ```
   `update` uses partial semantics: omitted keys are left untouched; an explicit
   `null` clears a field. The slug `id` never changes, even if you edit the `title`.
   Use the same command to fix a `body`/`title`/`tags` the user wants changed.
4. **Report** the idea id and its new value (e.g. `reputation 50 → 90`).

`reputation` is a single current score (latest judgment wins), not an average across
users — per-author reputation is a later addition.

**Delete.** To remove an idea: `python3 "$IDEAL" delete <id>` (its links cascade).
To remove one edge: `python3 "$IDEAL" unlink <source-id> <target-id> <similar|connected>`.
Deletion is irreversible — confirm with the user before deleting anything they did
not just ask to delete in the same breath.

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
