# IdeaL — a co-vibecode idea store where Claude is the search engine

IdeaL is a shared store of **atomic ideas**. One person brain-dumps thoughts; Claude
Code splits them into atomic ideas, decides how each relates to what's already stored,
links them, and saves them to a small server on a cloud VM. Another person reads and
queries the store — also through Claude.

**The defining constraint: there is no similarity algorithm anywhere.** No embeddings,
no RAG, no vector search, no keyword scoring — not on the server, not in the plugin.
The server is a dumb SQLite store plus a Markdown exporter. To find what's related,
Claude fetches the **entire store as one Markdown document** and **reads it**. Claude's
judgment *is* the search engine.

```
 Writer                                   VM (your cloud box)
 ┌────────────────────────┐  GET /export  ┌───────────────────────────┐
 │ Claude Code + `ideal`  │ ────────────► │ FastAPI + SQLite           │
 │ skill → ideal.py client │  POST /ideas  │  ideas + typed links       │
 └────────────────────────┘ ────────────► │  /export → one .md document │
 Reader ── GET /export ──────────────────►│  (reader never writes)      │
 └────────────────────────┘               └───────────────────────────┘
```

An idea is atomic (one claim/concept/question). Links are typed:
- **`similar`** — the ideas are about the same thing (near-duplicate, mergeable).
- **`connected`** — distinct ideas that relate (builds-on, motivates, contrasts…).

Ideas also carry metadata — `author`, `tags`, `task`, `usefulness`, `reputation`,
`status`, and an extensible `meta` blob. Most are nullable and left null for now; the
schema makes room to populate them later.

---

## Repository layout

```
IdeaL/
├── .claude-plugin/        # marketplace.json + plugin.json (the installable plugin)
├── skills/ideal/          # SKILL.md (the workflow) + scripts/ideal.py (stdlib client)
├── commands/              # /ideal-setup, /ideal-add, /ideal-read
├── server/                # FastAPI app, SQLite schema, exporter, tests, Dockerfile
├── deploy/docker-compose.yml
├── scripts/               # deploy.sh + smoke-test.sh (run on the VM; not installed)
├── .env.example           # server config template
└── README.md
```

The plugin lives at the repo root; `server/` and `deploy/` are **not** copied when the
plugin is installed — they run on the VM.

---

## 1. Deploy the server (on your existing VM)

This repo does not provision a machine — it deploys the server onto a VM you already
run. On the VM:

```sh
git clone <this-repo-url> IdeaL && cd IdeaL
cp .env.example .env
# edit .env: set IDEAL_TOKEN to a long random secret, e.g. openssl rand -hex 32
./scripts/deploy.sh          # docker compose up -d --build, SQLite persisted to ./data
./scripts/smoke-test.sh      # optional: health + add/export round-trip
```

**No Docker on the VM?** Install it once (Docker Engine + compose plugin, via
Docker's official script), then deploy:

```sh
./scripts/install-docker.sh  # needs sudo/root; adds you to the docker group
newgrp docker                # or log out/in so group membership takes effect
./scripts/deploy.sh          # (or: sudo ./scripts/deploy.sh, no re-login needed)
```

Then **open `IDEAL_PORT` (default 8000) in the VM's firewall / security group** so the
machine running Claude Code can reach it.

**Security note.** The bearer token is the *only* access control, and traffic is plain
HTTP. That's acceptable on a trusted network. If the VM is exposed to the internet, put
it behind TLS (a reverse proxy) or a tunnel — out of scope for v1. Reads require the
token by default (`IDEAL_PROTECT_READS=true`), since `/export` dumps the whole store.

Local dev (no Docker):

```sh
cd server
pip install -r requirements.txt
IDEAL_TOKEN=dev IDEAL_DB_PATH=./ideal.sqlite uvicorn app:app --reload
```

### Server configuration (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `IDEAL_TOKEN` | *(required)* | Shared bearer token. No token → server refuses to start. |
| `IDEAL_PORT` | `8000` | Host port to expose (open it in the firewall). |
| `IDEAL_DB_PATH` | `/data/ideal.sqlite` | SQLite path inside the container (persisted to `./data`). |
| `IDEAL_PROTECT_READS` | `true` | Require the token on read endpoints too. |
| `IDEAL_ON_UNKNOWN_TARGET` | `reject` | `reject` = refuse ideas linking to unknown targets; `ignore` = drop those edges. |

---

## 2. Install the plugin (each user)

```
/plugin marketplace add <this-repo-url>
/plugin install ideal
/ideal-setup            # enter the server URL, the shared token, and your author name
```

`/ideal-setup` writes `~/.config/ideal/config.env` (chmod 600). The token is never
printed back. You can override any value with the `IDEAL_URL` / `IDEAL_TOKEN` /
`IDEAL_AUTHOR` environment variables.

---

## 3. Use it

**Add ideas** (writer):

```
/ideal-add I think our idea store should use SQLite because it's zero-ops on a single
VM. Also, Claude should decide the links by reading everything — not embeddings.
```

Claude splits that into atomic ideas, reads the **whole** store, checks for duplicates,
decides `similar`/`connected` links by reasoning over what it read, writes each idea,
and reports the new ids and their edges. (You can also just say "save this to IdeaL"
or "capture this thought" — the skill triggers without the slash command.)

**Read / query** (reader):

```
/ideal-read what's stored about our datastore choice?
```

Claude fetches the store, reads it, and answers in prose citing idea ids — **writing
nothing**. Whole-store questions ("summarize the themes", "what has alice been
exploring") and targeted ones ("show idea `use-sqlite-for-zero-ops`") both work.

### The client CLI (used by the skill; handy for debugging)

```
python3 skills/ideal/scripts/ideal.py health
python3 skills/ideal/scripts/ideal.py export            # whole store as Markdown
python3 skills/ideal/scripts/ideal.py list              # id / title / tags index
python3 skills/ideal/scripts/ideal.py get <id>          # one idea + its links
echo '{"title":"...","body":"...","tags":["x"]}' | python3 skills/ideal/scripts/ideal.py add
```

Python 3 standard library only — no pip, curl, or jq needed on the client.

---

## HTTP API

Auth: `Authorization: Bearer <IDEAL_TOKEN>` on writes and (by default) reads; `/health`
is open. Errors use a `{"error","detail"}` envelope.

| Method / path | Purpose |
|---|---|
| `GET /health` | liveness + `{ideas, links}` counts |
| `GET /export` | **whole store as one Markdown doc** (`?format=json` for a structured dump) |
| `GET /ideas` | list ids, titles, tags |
| `GET /ideas/{id}` | one idea + `links_out`/`links_in` (`?format=md`) |
| `POST /ideas` | add one idea **and** its edges atomically → `{id, edges_created}` |
| `POST /links` | link two existing ideas (idempotent) |

Adding an idea whose edge points at an unknown `target_id` **rejects the whole request**
(422, rolled back) by default, so Claude never records a link to something that doesn't
exist.

---

## Testing

```sh
cd server
pip install -r requirements-dev.txt
pytest tests/ -q            # no network or Docker needed
```

The suite drives the public HTTP surface with a throwaway SQLite file: health, auth
rejection, add→export, edge rendering (`[[id]]` + `**connected**` + note), unknown-target
rollback, link idempotency, slug collision suffixes, and the exact export line format.

---

## License

MIT — see [LICENSE](LICENSE).
