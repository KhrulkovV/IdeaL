---
description: Semantic GraphRAG search over IdeaL — pull a focused slice by meaning, then reason over it.
argument-hint: "[semantic query]"
---

Semantically retrieve the ideas most relevant to: $ARGUMENTS

This is the **optional, read-only** GraphRAG layer (the `rag/` package). Unlike `/ideal:ideal-read`
— which reads the *whole* store — this embeds the query, seeds by vector similarity, then follows
the `[[target-id]]` `similar`/`connected` wikilinks to pull in each seed's neighbourhood. Use it to
get a relevant sub-slice instead of the entire export. It **never writes** — no ideas, no links.

## Run it

If `$ARGUMENTS` is empty, ask the user what they want to search for and stop.

Otherwise run the search CLI (the `rag` package lives at the plugin root; it auto-locates the
`ideal.py` client and its config):

```bash
PYTHONPATH="$CLAUDE_PLUGIN_ROOT" python3 -m rag.search "$ARGUMENTS"
```

Tune retrieval when the user asks for broader or tighter results (defaults `--start-k 4 --hops 1`):
- `--start-k N` — how many ideas vector similarity seeds.
- `--hops N` — how far to walk the wikilinks (`--hops 0` = plain vector search, no graph).
- `--json` — machine-readable `{query, results, context}` if you need to post-process.

## Then present

The CLI prints a ranked list (each idea tagged `seed · score` or `reached · N hop out`) followed by
a `--- context block ---` of the retrieved ideas. Show the user the ranked hits, then — since this
is an interactive command — briefly answer their query by reasoning over the retrieved slice, citing
idea ids. Note which ideas were **reached via a link** rather than by matching text: those are the
non-obvious connections the graph surfaced.

## If it errors

- `ModuleNotFoundError` / import errors → the semantic layer's dependencies aren't installed. Tell
  the user to run `pip install -r "$CLAUDE_PLUGIN_ROOT/rag/requirements.txt"` once (it pulls
  sentence-transformers/torch; the first search also downloads the MiniLM model ~90 MB).
- Config / auth error → the client isn't set up; tell them to run `/ideal:ideal-setup` first.
