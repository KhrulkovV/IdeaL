---
description: Read and query the IdeaL store — Claude reads the whole store and answers.
argument-hint: "[question about the store]"
---

Answer a question about the IdeaL store. The question is: $ARGUMENTS

Use the **ideal** skill and follow its **Flow B — READ** exactly: fetch the store with
`ideal.py export` (or `list` / `get <id>` for targeted lookups), read it, and answer in
prose citing idea ids. This flow is **read-only** — do not add ideas or create links.

If `$ARGUMENTS` is empty, ask the user what they want to know (e.g. a summary, a topic,
an author, or a specific idea id). If the client is not configured, tell them to run
`/ideal:ideal-setup` first.
