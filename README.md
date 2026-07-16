# IdeaL — a co-vibecode idea store where Claude is the search engine

IdeaL is a shared store of **atomic ideas**. One person brain-dumps thoughts; Claude
Code splits them into atomic ideas, decides how each relates to what's already stored,
links them, and saves them to a small server on a cloud VM. Another person reads and
queries the store — also through Claude.

**The defining constraint: no algorithm decides how ideas relate.** No embeddings, no
vector search, no keyword scoring picks the links — Claude does, by reading the whole
store. The server is a dumb SQLite store plus a Markdown exporter; to find what's
related, Claude fetches the **entire store as one Markdown document** and **reads it**.
Claude's judgment *is* the linker.

> **One deliberate, opt-in exception:** an *additive, read-only* semantic index on the
> VM powers `POST /search` (`/ideal-search`) for pulling a relevant sub-slice by meaning
> when the store grows past what's comfortable to read whole. It **never creates links** —
> it embeds idea text and traverses the links Claude already authored — and it's off with
> `IDEAL_RAG_ENABLED=false`. The core add/link/read flow above is untouched. See
> `docs/superpowers/specs/2026-07-16-server-side-rag-design.md`.

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

## Quickstart — join an existing store (teammates)

If a colleague already runs an IdeaL server and has given you its **URL**, the shared
**token**, and told you to pick an **author name**, the plugin is all you install:

```
/plugin marketplace add KhrulkovV/IdeaL   # this public repo — no clone needed
/plugin install ideal
/reload-plugins                           # activate the plugin without restarting
/ideal:ideal-setup                        # paste the URL + token, set your author name
```

Plugin commands are **namespaced under the plugin name**, so they are
`/ideal:ideal-setup`, `/ideal:ideal-add`, and `/ideal:ideal-read` (a bare
`/ideal-setup` will report "Unknown command"). You can also skip the slash commands
entirely and just talk to Claude — "save this to IdeaL", "what's stored about X?",
"this idea is solid" — the skill triggers on its own. The plugin is a pure client
(Python standard library only — no pip, curl, or jq), so there is nothing else to set up.

The URL and token come from whoever runs the store and are shared privately — they are
**not** in this repo. `/ideal:ideal-setup` writes them to `~/.config/ideal/config.env`
(chmod 600) and never prints the token back.

---

## Repository layout

```
IdeaL/
├── .claude-plugin/        # marketplace.json + plugin.json (the installable plugin)
├── skills/ideal/          # SKILL.md (the workflow) + scripts/ideal.py (stdlib client)
├── commands/              # /ideal:ideal-setup, /ideal:ideal-add, /ideal:ideal-read
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

**No root at all (can't install Docker)?** Run the server directly with Python in
your **active conda env** — no Docker, no sudo, no virtualenv. Dependencies install
into whatever env is active:

```sh
conda activate <your-env>    # deps install here; activate before starting
cp .env.example .env         # set IDEAL_TOKEN
./scripts/run.sh start       # installs deps into the active env, starts uvicorn
./scripts/run.sh status      # running? PID?
./scripts/run.sh logs        # follow the log
./scripts/run.sh stop
```

The runner uses the active interpreter (`$CONDA_PREFIX`), or set
`IDEAL_PYTHON=$(conda run -n <env> which python)` to point at one without activating.
SQLite persists to `./data/ideal.sqlite`, logs to `./data/ideal.log`. The process
survives your SSH session (it's `nohup`ed); to restart it automatically after a VM
reboot without root, add a user crontab line: `@reboot cd /path/to/IdeaL && ./scripts/run.sh start`.

### Redeploying after a code update

Pull and restart in place — the SQLite file and the model cache persist:

```sh
cd IdeaL && git pull

# conda / Python-direct (no Docker):
conda activate <your-env>
./scripts/run.sh restart     # installs any new deps into the active env, then restarts

# Docker (if you use it instead):
./scripts/deploy.sh          # rebuilds the image (installs new deps), restarts
```

On the conda path, `run.sh` now installs the semantic-search deps into your active env when
`IDEAL_RAG_ENABLED` is true: it installs a **CPU torch wheel by default** (so the multi-GB CUDA
build isn't pulled in) plus `sentence-transformers`/`numpy`. To change that: set
`IDEAL_TORCH_INDEX_URL=<url>` (empty string = pip's default/GPU index), or pre-install torch
yourself (`conda install pytorch cpuonly -c pytorch`) and the step is skipped. When
`IDEAL_RAG_ENABLED=false`, no ML stack is installed at all.

The first start with search enabled downloads the embedding model (~90 MB — cached under
`~/.cache/huggingface` on the host, or `./data/hf-cache` under Docker) and backfills embeddings
for every existing idea before serving, so that first boot can take a couple of minutes; later
restarts load the stored vectors instantly. The schema migration (three nullable columns on
`ideas`) is applied automatically and idempotently.

### Reaching the server from another machine

The client needs to reach `IDEAL_PORT` (default 8000) on the VM. Two options:

**SSH tunnel (recommended — no firewall changes, no root, encrypted).** If you can
SSH to the VM, forward the port from the machine running Claude Code:

```sh
ssh -N -L 8000:127.0.0.1:8000 <user>@<vm-ip>
# then point the client at the tunnel:  /ideal:ideal-setup  ->  http://127.0.0.1:8000
```

This keeps the plain-HTTP, token-only endpoint off the public internet.

**Open the port (public access).** Allow `IDEAL_PORT` in *every* firewall layer:
- Host firewall, e.g. `ufw`:  `sudo ufw allow 8000/tcp`  (needs root; check with `systemctl is-active ufw`).
- Cloud firewall (DigitalOcean/AWS/GCP security group): add an inbound TCP rule for the port in the provider console.

Diagnosing a block: from *outside*, a **timeout** on the port means a firewall is
dropping packets (vs. "connection refused" = nothing listening). On the VM,
`curl http://127.0.0.1:8000/health` proves the app is fine; `ss -tlnp | grep 8000`
should show `0.0.0.0:8000`.

**Security note.** The bearer token is the *only* access control, and traffic is plain
HTTP. That's acceptable on a trusted network or through the SSH tunnel above. If you
expose the port to the internet, put it behind TLS (a reverse proxy) — out of scope
for v1. Reads require the token by default (`IDEAL_PROTECT_READS=true`), since
`/export` dumps the whole store.

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
| `IDEAL_HOST` | `0.0.0.0` | Bind interface on the `run.sh` (no-Docker) path; `127.0.0.1` = loopback only. Under Docker the container always binds `0.0.0.0` internally. |
| `IDEAL_DB_PATH` | `/data/ideal.sqlite` | SQLite path inside the container (persisted to `./data`). |
| `IDEAL_PROTECT_READS` | `true` | Require the token on read endpoints too. |
| `IDEAL_ON_UNKNOWN_TARGET` | `reject` | `reject` = refuse ideas linking to unknown targets; `ignore` = drop those edges. |
| `IDEAL_RAG_ENABLED` | `true` | Server-side semantic search (`POST /search`). `false` = no model, `/search` returns 503. |
| `IDEAL_RAG_MODEL` | `all-MiniLM-L6-v2` | sentence-transformers model for embeddings (changing it re-embeds on next boot). |

---

## 2. Install the plugin (each user)

```
/plugin marketplace add KhrulkovV/IdeaL     # public repo — no clone needed
/plugin install ideal
/reload-plugins         # activate the plugin without restarting
/ideal:ideal-setup      # enter the server URL, the shared token, and your author name
```

Plugin commands are namespaced under the plugin, so use `/ideal:ideal-setup`,
`/ideal:ideal-add`, `/ideal:ideal-read` (not the bare names). `/ideal:ideal-setup`
writes `~/.config/ideal/config.env` (chmod 600); the token is never printed back. You
can override any value with the `IDEAL_URL` / `IDEAL_TOKEN` / `IDEAL_AUTHOR`
environment variables.

---

## 3. Use it

**Add ideas** (writer):

```
/ideal:ideal-add I think our idea store should use SQLite because it's zero-ops on a
single VM. Also, Claude should decide the links by reading everything — not embeddings.
```

Claude splits that into atomic ideas, reads the **whole** store, checks for duplicates,
decides `similar`/`connected` links by reasoning over what it read, writes each idea,
and reports the new ids and their edges. (You can also just say "save this to IdeaL"
or "capture this thought" — the skill triggers without the slash command.)

**Read / query** (reader):

```
/ideal:ideal-read what's stored about our datastore choice?
```

Claude fetches the store, reads it, and answers in prose citing idea ids — **writing
nothing**. Whole-store questions ("summarize the themes", "what has alice been
exploring") and targeted ones ("show idea `use-sqlite-for-zero-ops`") both work.

### The client CLI (used by the skill; handy for debugging)

```
python3 skills/ideal/scripts/ideal.py health
python3 skills/ideal/scripts/ideal.py export            # whole store as Markdown
python3 skills/ideal/scripts/ideal.py list              # id / title / tags index (--json for machine-readable)
python3 skills/ideal/scripts/ideal.py get <id>          # one idea + its links
python3 skills/ideal/scripts/ideal.py search "query"    # server-side semantic search (needs IDEAL_RAG_ENABLED)
echo '{"title":"...","body":"...","tags":["x"]}' | python3 skills/ideal/scripts/ideal.py add
echo '{"reputation":90,"body":"revised"}' | python3 skills/ideal/scripts/ideal.py update <id>
python3 skills/ideal/scripts/ideal.py rate <id> 90 [--field reputation|usefulness]   # 0–100 score
python3 skills/ideal/scripts/ideal.py link <src> <tgt> similar|connected [--note "why"]
python3 skills/ideal/scripts/ideal.py delete <id>       # remove an idea (links cascade)
python3 skills/ideal/scripts/ideal.py unlink <src> <tgt> similar|connected
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
| `POST /search` | *(optional)* semantic GraphRAG: vector-seed + link-traverse → `{query, results, context}` |
| `POST /ideas` | add one idea **and** its edges atomically → `{id, edges_created}` |
| `PATCH /ideas/{id}` | partial update; only supplied fields change, `id` is immutable → the updated idea |
| `DELETE /ideas/{id}` | delete one idea; its links cascade → `{deleted}` |
| `POST /links` | link two existing ideas (idempotent) |
| `DELETE /links` | remove one edge `{source_id, target_id, type}` → `{deleted}` |

`PATCH` uses true partial semantics: an omitted key is left untouched, while an
explicit `null` clears a nullable field. `title`/`body` cannot be blanked, and the
slug `id` never changes even when the title does.

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
