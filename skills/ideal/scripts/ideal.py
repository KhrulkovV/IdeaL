#!/usr/bin/env python3
"""ideal.py — tiny stdlib client for the IdeaL store. No third-party deps.

Commands:
  health                 liveness check (server up?); does NOT verify your token
  export [--format md|json]   fetch the WHOLE store as one document (default md)
  list [--json]          list ideas (id, title, tags, scores)
  get <id> [--format]    fetch one idea + its edges
  add                    read one idea JSON object from STDIN and POST it
  update <id>            read a partial idea JSON from STDIN and PATCH it
  rate <id> <0-100> [--field reputation|usefulness]   set a score (default reputation)
  delete <id>            delete one idea (its links cascade)
  link <src> <tgt> <type> [--note]     link two existing ideas (type: similar|connected)
  unlink <src> <tgt> <type>   delete one edge (type: similar|connected)
  search <query> [--k --start-k --hops --json]   semantic GraphRAG search
  config --url --token --author   write client config (never prints the token)

Config resolution (per key, first found wins):
  1. environment: IDEAL_URL / IDEAL_TOKEN / IDEAL_AUTHOR
  2. file: $IDEAL_CONFIG, else ~/.config/ideal/config.env  (KEY=VALUE lines)
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_CONFIG = os.path.expanduser("~/.config/ideal/config.env")


def _config_path():
    return os.environ.get("IDEAL_CONFIG", DEFAULT_CONFIG)


def _read_config_file():
    values = {}
    try:
        with open(_config_path(), "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                values[key.strip()] = val.strip()
    except FileNotFoundError:
        pass
    return values


def load_config():
    file_vals = _read_config_file()

    def pick(key):
        return os.environ.get(key) or file_vals.get(key)

    return {
        "url": (pick("IDEAL_URL") or "").rstrip("/"),
        "token": pick("IDEAL_TOKEN") or "",
        "author": pick("IDEAL_AUTHOR") or "",
    }


def _die(msg, code=1):
    print(f"ideal: {msg}", file=sys.stderr)
    sys.exit(code)


def _require_config(cfg, need_token=True):
    if not cfg["url"]:
        _die("no server URL configured. Run /ideal-setup (or set IDEAL_URL).", 2)
    if need_token and not cfg["token"]:
        _die("no token configured. Run /ideal-setup (or set IDEAL_TOKEN).", 2)


def _request(cfg, method, path, query=None, body=None):
    url = cfg["url"] + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if cfg["token"]:
        headers["Authorization"] = "Bearer " + cfg["token"]
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        _die(f"cannot reach server at {cfg['url']}: {exc.reason}", 2)


def _print_text(text):
    sys.stdout.write(text if text.endswith("\n") else text + "\n")


# --- commands ----------------------------------------------------------------

def cmd_health(cfg, _args):
    _require_config(cfg, need_token=False)
    status, text = _request(cfg, "GET", "/health")
    if status == 200:
        try:
            j = json.loads(text)
            print(f"OK — {j.get('ideas', '?')} ideas, {j.get('links', '?')} links at {cfg['url']}")
        except json.JSONDecodeError:
            print("OK")
        return 0
    _die(f"health check failed ({status}): {text}", 1)


def cmd_export(cfg, args):
    _require_config(cfg)
    status, text = _request(cfg, "GET", "/export", query={"format": args.format})
    if status != 200:
        _die(f"export failed ({status}): {text}", 1)
    _print_text(text)
    return 0


def cmd_list(cfg, args):
    _require_config(cfg)
    status, text = _request(cfg, "GET", "/ideas")
    if status != 200:
        _die(f"list failed ({status}): {text}", 1)
    data = json.loads(text)
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0
    ideas = data.get("ideas", [])
    if not ideas:
        print("(store is empty)")
        return 0
    for i in ideas:
        tags = ", ".join(i.get("tags") or [])
        tag_part = f"  [{tags}]" if tags else ""
        scores = []
        if i.get("reputation") is not None:
            scores.append(f"rep {i['reputation']}")
        if i.get("usefulness") is not None:
            scores.append(f"use {i['usefulness']}")
        score_part = f"  ({', '.join(scores)})" if scores else ""
        print(f"{i['id']}  —  {i['title']}{tag_part}{score_part}")
    return 0


def cmd_get(cfg, args):
    _require_config(cfg)
    path = "/ideas/" + urllib.parse.quote(args.id)
    status, text = _request(cfg, "GET", path, query={"format": args.format})
    if status == 404:
        _die(f"no idea with id '{args.id}'", 1)
    if status != 200:
        _die(f"get failed ({status}): {text}", 1)
    if args.format == "json":
        print(json.dumps(json.loads(text), indent=2, ensure_ascii=False))
    else:
        _print_text(text)
    return 0


def cmd_add(cfg, args):
    _require_config(cfg)
    raw = sys.stdin.read()
    if not raw.strip():
        _die("no JSON on stdin. Pipe an idea object to `ideal.py add`.", 1)
    try:
        idea = json.loads(raw)
    except json.JSONDecodeError as exc:
        _die(f"invalid JSON on stdin: {exc}", 1)
    if not isinstance(idea, dict):
        _die("stdin JSON must be an object", 1)
    if not idea.get("title") or not idea.get("body"):
        _die("idea requires non-empty 'title' and 'body'", 1)
    if not idea.get("author") and cfg["author"]:
        idea["author"] = cfg["author"]
    for edge in idea.get("edges") or []:
        if isinstance(edge, dict) and edge.get("type") not in ("similar", "connected"):
            _die(f"edge type must be 'similar' or 'connected', got {edge.get('type')!r}", 1)

    query = {"on_unknown_target": args.on_unknown_target} if args.on_unknown_target else None
    status, text = _request(cfg, "POST", "/ideas", query=query, body=idea)
    if status not in (200, 201):
        _die(f"add failed ({status}): {text}", 1)
    result = json.loads(text)
    print(result["id"])  # id alone on stdout, so callers can capture it cleanly
    created = result.get("edges_created", 0)
    ignored = result.get("edges_ignored") or []
    if created or ignored:
        parts = [f"{created} edge(s) created"]
        if ignored:
            parts.append(f"dropped unknown target(s): {', '.join(ignored)}")
        print("ideal: " + "; ".join(parts), file=sys.stderr)
    return 0


def cmd_update(cfg, args):
    _require_config(cfg)
    raw = sys.stdin.read()
    if not raw.strip():
        _die("no JSON on stdin. Pipe the fields to change to `ideal.py update <id>`.", 1)
    try:
        patch = json.loads(raw)
    except json.JSONDecodeError as exc:
        _die(f"invalid JSON on stdin: {exc}", 1)
    if not isinstance(patch, dict):
        _die("stdin JSON must be an object", 1)
    if not patch:
        _die("no fields to update", 1)
    path = "/ideas/" + urllib.parse.quote(args.id)
    status, text = _request(cfg, "PATCH", path, body=patch)
    if status == 404:
        _die(f"no idea with id '{args.id}'", 1)
    if status != 200:
        _die(f"update failed ({status}): {text}", 1)
    print(json.loads(text)["id"])
    return 0


def cmd_rate(cfg, args):
    _require_config(cfg)
    if not 0 <= args.score <= 100:
        _die(f"score must be between 0 and 100, got {args.score}", 1)
    path = "/ideas/" + urllib.parse.quote(args.id)
    status, text = _request(cfg, "PATCH", path, body={args.field: args.score})
    if status == 404:
        _die(f"no idea with id '{args.id}'", 1)
    if status != 200:
        _die(f"rate failed ({status}): {text}", 1)
    print(f"{args.id}: {args.field} = {json.loads(text).get(args.field)}")
    return 0


def cmd_link(cfg, args):
    _require_config(cfg)
    if args.type not in ("similar", "connected"):
        _die(f"type must be 'similar' or 'connected', got {args.type!r}", 1)
    body = {
        "source_id": args.source, "target_id": args.target,
        "type": args.type, "note": args.note or "",
    }
    status, text = _request(cfg, "POST", "/links", body=body)
    if status == 422:
        _die(f"link failed: unknown idea id in ({args.source!r}, {args.target!r})", 1)
    if status not in (200, 201):
        _die(f"link failed ({status}): {text}", 1)
    print("created" if json.loads(text).get("created") else "already linked")
    return 0


def cmd_delete(cfg, args):
    _require_config(cfg)
    path = "/ideas/" + urllib.parse.quote(args.id)
    status, text = _request(cfg, "DELETE", path)
    if status == 404:
        _die(f"no idea with id '{args.id}'", 1)
    if status != 200:
        _die(f"delete failed ({status}): {text}", 1)
    print(f"deleted {args.id}")
    return 0


def cmd_unlink(cfg, args):
    _require_config(cfg)
    if args.type not in ("similar", "connected"):
        _die(f"type must be 'similar' or 'connected', got {args.type!r}", 1)
    body = {"source_id": args.source, "target_id": args.target, "type": args.type}
    status, text = _request(cfg, "DELETE", "/links", body=body)
    if status != 200:
        _die(f"unlink failed ({status}): {text}", 1)
    print("deleted" if json.loads(text).get("deleted") else "no such link")
    return 0


def cmd_search(cfg, args):
    _require_config(cfg)
    body = {"query": args.query, "k": args.k, "start_k": args.start_k, "hops": args.hops}
    status, text = _request(cfg, "POST", "/search", body=body)
    if status == 503:
        _die("semantic search is disabled on this server (set IDEAL_RAG_ENABLED=true).", 3)
    if status != 200:
        _die(f"search failed ({status}): {text}", 1)
    data = json.loads(text)
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0
    results = data.get("results", [])
    if not results:
        print("(no matches)")
        return 0
    for h in results:
        if h.get("depth", 0) == 0:
            score = h.get("score")
            tag = f"seed · {score:.3f}" if isinstance(score, (int, float)) else "seed"
        else:
            tag = h.get("reason") or f"reached · {h['depth']} hop out"
        tags = ", ".join(h.get("tags") or [])
        tag_part = f"  [{tags}]" if tags else ""
        print(f"{h['id']}  —  {h['title']}  ({tag}){tag_part}")
    ctx = data.get("context") or ""
    if ctx:
        print("\n--- context block ---\n")
        _print_text(ctx)
    return 0


def cmd_config(_cfg, args):
    path = _config_path()
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    existing = _read_config_file()
    if args.url:
        existing["IDEAL_URL"] = args.url.rstrip("/")
    if args.token:
        existing["IDEAL_TOKEN"] = args.token
    if args.author:
        existing["IDEAL_AUTHOR"] = args.author

    body = "\n".join([
        "# IdeaL client config. Written by /ideal-setup. Keep this file private.",
        f"IDEAL_URL={existing.get('IDEAL_URL', '')}",
        f"IDEAL_TOKEN={existing.get('IDEAL_TOKEN', '')}",
        f"IDEAL_AUTHOR={existing.get('IDEAL_AUTHOR', '')}",
        "",
    ])
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    os.chmod(path, 0o600)
    author = existing.get("IDEAL_AUTHOR", "") or "(no author)"
    print(f"configured: {existing.get('IDEAL_URL', '')} as {author} ({path})")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="ideal",
        description="Stdlib client for the IdeaL atomic-idea store.",
        epilog="Config: IDEAL_URL / IDEAL_TOKEN / IDEAL_AUTHOR "
               "(env, or ~/.config/ideal/config.env via /ideal-setup).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True, metavar="<command>")

    sub.add_parser("health", help="liveness check (does NOT verify your token)")
    p_export = sub.add_parser("export", help="fetch the whole store as one document")
    p_export.add_argument("--format", choices=["md", "json"], default="md")
    p_list = sub.add_parser("list", help="list ideas (id, title, tags, scores)")
    p_list.add_argument("--json", action="store_true", help="emit the raw JSON response")
    p_get = sub.add_parser("get", help="fetch one idea and its edges")
    p_get.add_argument("id")
    p_get.add_argument("--format", choices=["md", "json"], default="json")
    p_add = sub.add_parser("add", help="add one idea read as JSON from stdin")
    p_add.add_argument("--on-unknown-target", choices=["reject", "ignore"], default=None,
                       dest="on_unknown_target")
    p_update = sub.add_parser("update", help="patch one idea with JSON fields from stdin")
    p_update.add_argument("id")
    p_rate = sub.add_parser("rate", help="set an idea's reputation/usefulness score (0-100)")
    p_rate.add_argument("id")
    p_rate.add_argument("score", type=int)
    p_rate.add_argument("--field", choices=["reputation", "usefulness"], default="reputation")
    p_delete = sub.add_parser("delete", help="delete one idea (its links cascade)")
    p_delete.add_argument("id")
    p_link = sub.add_parser("link", help="link two existing ideas (idempotent)")
    p_link.add_argument("source")
    p_link.add_argument("target")
    p_link.add_argument("type", choices=["similar", "connected"])
    p_link.add_argument("--note", default="")
    p_unlink = sub.add_parser("unlink", help="delete one edge")
    p_unlink.add_argument("source")
    p_unlink.add_argument("target")
    p_unlink.add_argument("type", choices=["similar", "connected"])
    p_search = sub.add_parser("search", help="semantic GraphRAG search")
    p_search.add_argument("query")
    p_search.add_argument("--k", type=int, default=8)
    p_search.add_argument("--start-k", type=int, default=4, dest="start_k")
    p_search.add_argument("--hops", type=int, default=1)
    p_search.add_argument("--json", action="store_true")
    p_config = sub.add_parser("config", help="write client config (never prints the token)")
    p_config.add_argument("--url")
    p_config.add_argument("--token")
    p_config.add_argument("--author")

    args = parser.parse_args(argv)
    handlers = {
        "health": cmd_health,
        "export": cmd_export,
        "list": cmd_list,
        "get": cmd_get,
        "add": cmd_add,
        "update": cmd_update,
        "rate": cmd_rate,
        "delete": cmd_delete,
        "link": cmd_link,
        "unlink": cmd_unlink,
        "search": cmd_search,
        "config": cmd_config,
    }
    return handlers[args.cmd](load_config(), args)


if __name__ == "__main__":
    sys.exit(main())
