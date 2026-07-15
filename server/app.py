"""IdeaL HTTP API: a dumb SQLite store + markdown exporter.

All similarity/connection reasoning happens Claude-side. This server only stores
atomic ideas and typed edges, and renders the whole store as one markdown doc.
"""
import json
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

import config
import db
import ids
from export import render_json, render_markdown
from models import IdeaCreate, LinkCreate


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_schema()
    yield


app = FastAPI(title="IdeaL", version="0.1.0", lifespan=lifespan)


# --- auth --------------------------------------------------------------------

def _check_token(authorization: Optional[str]) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={"error": "unauthorized", "detail": "missing or malformed bearer token"},
        )
    token = authorization.split(" ", 1)[1].strip()
    if token != config.settings.token:
        raise HTTPException(
            status_code=401,
            detail={"error": "unauthorized", "detail": "invalid token"},
        )


def auth_write(authorization: Optional[str] = Header(default=None, alias="Authorization")) -> None:
    _check_token(authorization)


def auth_read(authorization: Optional[str] = Header(default=None, alias="Authorization")) -> None:
    if config.settings.protect_reads:
        _check_token(authorization)


@app.exception_handler(StarletteHTTPException)
async def _http_exception_handler(_request, exc: StarletteHTTPException):
    detail = exc.detail
    if isinstance(detail, dict) and "error" in detail:
        return JSONResponse(status_code=exc.status_code, content=detail)
    return JSONResponse(status_code=exc.status_code, content={"error": "http_error", "detail": detail})


# --- health ------------------------------------------------------------------

@app.get("/health")
def health():
    conn = db.connect()
    try:
        ideas, links = db.counts(conn)
    finally:
        conn.close()
    return {"status": "ok", "ideas": ideas, "links": links}


# --- reads -------------------------------------------------------------------

@app.get("/export", dependencies=[Depends(auth_read)])
def export(format: str = Query(default="md")):
    conn = db.connect()
    try:
        ideas = db.fetch_all_ideas(conn)
        links = db.fetch_all_links(conn)
    finally:
        conn.close()
    generated_at = db.now_iso()
    if format == "json":
        return Response(
            content=render_json(ideas, links, generated_at),
            media_type="application/json",
        )
    return PlainTextResponse(
        content=render_markdown(ideas, links, generated_at),
        media_type="text/markdown",
    )


@app.get("/ideas", dependencies=[Depends(auth_read)])
def get_ideas():
    conn = db.connect()
    try:
        rows = db.list_ideas(conn)
    finally:
        conn.close()
    return {
        "ideas": [
            {
                "id": r["id"],
                "title": r["title"],
                "tags": ids.split_tags(r["tags"]),
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]
    }


@app.get("/ideas/{idea_id}", dependencies=[Depends(auth_read)])
def get_idea(idea_id: str, format: str = Query(default="json")):
    conn = db.connect()
    try:
        row = db.fetch_idea(conn, idea_id)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "not_found", "detail": f"no idea with id '{idea_id}'"},
            )
        links_out = db.fetch_links_out(conn, idea_id)
        links_in = db.fetch_links_in(conn, idea_id)
    finally:
        conn.close()

    if format == "md":
        edges = [
            {"source_id": idea_id, "target_id": l["target_id"], "type": l["type"], "note": l["note"]}
            for l in links_out
        ]
        return PlainTextResponse(
            content=render_markdown([row], edges, db.now_iso()),
            media_type="text/markdown",
        )

    return {
        "id": row["id"],
        "title": row["title"],
        "body": row["body"],
        "author": row["author"],
        "tags": ids.split_tags(row["tags"]),
        "task": row["task"],
        "usefulness": row["usefulness"],
        "reputation": row["reputation"],
        "status": row["status"],
        "meta": json.loads(row["meta"]) if row["meta"] else None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "links_out": [
            {"target_id": l["target_id"], "type": l["type"], "note": l["note"]} for l in links_out
        ],
        "links_in": [
            {"source_id": l["source_id"], "type": l["type"], "note": l["note"]} for l in links_in
        ],
    }


# --- writes ------------------------------------------------------------------

@app.post("/ideas", status_code=201, dependencies=[Depends(auth_write)])
def create_idea(
    payload: IdeaCreate,
    response: Response,
    on_unknown_target: Optional[str] = Query(default=None),
):
    mode = (on_unknown_target or config.settings.on_unknown_target).lower()
    if mode not in ("reject", "ignore"):
        mode = config.settings.on_unknown_target

    conn = db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")

        new_id = ids.unique_id(conn, payload.title)

        seen = set()
        unknown = []
        edges_to_insert = []
        for edge in payload.edges:
            key = (edge.target_id, edge.type)
            if key in seen:
                continue
            seen.add(key)
            if not db.idea_exists(conn, edge.target_id):
                unknown.append(edge.target_id)
                continue
            edges_to_insert.append(edge)

        if unknown and mode == "reject":
            conn.execute("ROLLBACK")
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "unknown_targets",
                    "detail": f"unknown target_id(s): {unknown}",
                    "unknown": unknown,
                },
            )

        when = db.now_iso()
        db.insert_idea(
            conn,
            new_id,
            {
                "title": payload.title,
                "body": payload.body,
                "author": payload.author,
                "tags": ids.normalize_tags(payload.tags),
                "task": payload.task,
                "usefulness": payload.usefulness,
                "reputation": payload.reputation,
                "status": payload.status,
                "meta": json.dumps(payload.meta) if payload.meta is not None else None,
            },
            when,
        )

        edges_created = 0
        for edge in edges_to_insert:
            if edge.target_id == new_id:
                continue  # fresh id can't collide, but never self-loop
            if db.insert_link(conn, new_id, edge.target_id, edge.type, edge.note, when):
                edges_created += 1

        conn.execute("COMMIT")
    except HTTPException:
        raise
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()

    response.headers["Location"] = f"/ideas/{new_id}"
    return {
        "id": new_id,
        "edges_created": edges_created,
        "edges_ignored": unknown if mode == "ignore" else [],
    }


@app.post("/links", status_code=201, dependencies=[Depends(auth_write)])
def create_link(payload: LinkCreate):
    if payload.source_id == payload.target_id:
        raise HTTPException(
            status_code=400,
            detail={"error": "self_loop", "detail": "source and target must differ"},
        )
    conn = db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        missing = [
            x for x in (payload.source_id, payload.target_id) if not db.idea_exists(conn, x)
        ]
        if missing:
            conn.execute("ROLLBACK")
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "unknown_targets",
                    "detail": f"unknown id(s): {missing}",
                    "unknown": missing,
                },
            )
        created = db.insert_link(
            conn, payload.source_id, payload.target_id, payload.type, payload.note, db.now_iso()
        )
        conn.execute("COMMIT")
    except HTTPException:
        raise
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()
    return {"created": created}
