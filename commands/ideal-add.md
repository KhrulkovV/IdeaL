---
description: Split a brain-dump into atomic ideas and add them to the IdeaL store with links.
argument-hint: "[your thoughts / brain-dump]"
---

Add ideas to the IdeaL store. The text to capture is: $ARGUMENTS

Use the **ideal** skill and follow its **Flow A — ADD** exactly:
split the text into atomic ideas, run `ideal.py export` and read the **whole** store,
check for duplicates, decide `similar`/`connected` links by reasoning over what you
read (never a keyword or similarity algorithm), then write each idea earliest-first and
report the new ids and their edges.

If `$ARGUMENTS` is empty, ask the user what they want to capture. If the client is not
configured, tell them to run `/ideal-setup` first.
