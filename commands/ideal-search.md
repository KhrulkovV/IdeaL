---
description: Semantic GraphRAG search over IdeaL — pull a focused slice by meaning, then reason over it.
argument-hint: "[semantic query]"
---

Semantically retrieve the ideas most relevant to: $ARGUMENTS

This is the **optional, read-only** GraphRAG layer. Unlike `/ideal:ideal-read` — which reads the
*whole* store — the server embeds the query, seeds by vector similarity, then follows the
`[[target-id]]` `similar`/`connected` wikilinks to pull in each seed's neighbourhood. Use it to get
a relevant sub-slice instead of the entire export. It **never writes** — no ideas, no links.

The engine runs **on the VM**: embeddings are computed once when each idea is written and held warm
server-side, so this command is a thin `POST /search` call — **no ML dependencies on this machine.**

## Run it

If `$ARGUMENTS` is empty, ask the user what they want to search for and stop.

Otherwise call the stdlib client (it reads the same config/auth as every other IdeaL command):

```bash
python3 "$CLAUDE_PLUGIN_ROOT/skills/ideal/scripts/ideal.py" search "$ARGUMENTS"
```

Tune retrieval when the user asks for broader or tighter results (defaults `--start-k 4 --hops 1`):
- `--start-k N` — how many ideas vector similarity seeds.
- `--hops N` — how far to walk the wikilinks (`--hops 0` = plain vector search, no graph).
- `--k N` — max ideas returned.
- `--json` — machine-readable `{query, results, context}` if you need to post-process.

## Then present

The CLI prints a ranked list (each idea tagged `seed · score` or `reached · N hop out`) followed by
a `--- context block ---` of the retrieved ideas. Show the user the ranked hits, then — since this
is an interactive command — briefly answer their query by reasoning over the retrieved slice, citing
idea ids. Note which ideas were **reached via a link** rather than by matching text: those are the
non-obvious connections the graph surfaced.

## If it errors

- `503` / "semantic search is disabled" → the server was started with `IDEAL_RAG_ENABLED=false`.
  Tell the user to enable it (redeploy the server with the flag set / unset) or fall back to
  `/ideal:ideal-read`.
- Config / auth error → the client isn't set up; tell them to run `/ideal:ideal-setup` first.
- Cannot reach server → the VM/port is down or unreachable; check `python3 …/ideal.py health`.
