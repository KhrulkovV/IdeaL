---
description: Configure the IdeaL client — server URL, shared token, and your author name.
argument-hint: "[server-url] [author]"
---

Configure this machine to talk to an IdeaL server. The config is written to
`~/.config/ideal/config.env` (chmod 600) and holds the server URL, the shared bearer
token, and an optional author name stamped on ideas you add.

Arguments (both optional): `$1` = server URL (e.g. `http://VM_IP:8000`), `$2` = author.

Steps:

1. Collect the three values. Use `$1` as the URL and `$2` as the author if provided.
   For anything missing, ask the user:
   - **Server URL** — where the IdeaL server runs, e.g. `http://<vm-ip>:8000`.
   - **Token** — the shared secret equal to the server's `IDEAL_TOKEN`. Ask the user to
     paste it. **Never echo it back, never write it to chat, never log it.**
   - **Author** — the name to stamp on ideas this user adds (optional).

2. Write the config with the helper (it never prints the token):
   ```
   python3 "$CLAUDE_PLUGIN_ROOT/skills/ideal/scripts/ideal.py" config \
     --url "<url>" --token "<token>" --author "<author>"
   ```
   Omit `--author` if the user did not give one.

3. Verify connectivity:
   ```
   python3 "$CLAUDE_PLUGIN_ROOT/skills/ideal/scripts/ideal.py" health
   ```
   On `OK …`, confirm setup is complete and the store is reachable. If it fails, report
   the error plainly (unreachable URL vs. bad token) and suggest the fix — do **not**
   print the token in either case.
