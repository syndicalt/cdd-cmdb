"""CMDB API Server — FastAPI + SQLite (in-process)."""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

_conn: sqlite3.Connection | None = None


def get_db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(":memory:", check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        init_db(_conn)
    return _conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS cis (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            attributes TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS relationships (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            type TEXT NOT NULL,
            attributes TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
    """)
    conn.commit()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_uuid() -> str:
    return str(uuid.uuid4())


def ci_row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    raw = d.get("attributes", "{}")
    d["attributes"] = json.loads(raw) if isinstance(raw, str) else {}
    return d


def rel_row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    raw = d.get("attributes", "{}")
    d["attributes"] = json.loads(raw) if isinstance(raw, str) else {}
    return d


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

def _check_attrs(v: Any) -> Any:
    """Reject any attribute value that is a dict or list."""
    if v is None:
        return v
    if not isinstance(v, dict):
        raise ValueError("attributes must be an object")
    for key, value in v.items():
        if isinstance(value, (dict, list)):
            raise ValueError(
                f"Attribute '{key}' must be a scalar (string, number, boolean, or null); "
                "nested objects and arrays are not permitted"
            )
    return v


class CIInput(BaseModel):
    name: str = Field(..., min_length=1)
    type: str = Field(..., min_length=1)
    attributes: Optional[dict[str, Any]] = Field(default=None)

    @field_validator("name", mode="before")
    @classmethod
    def name_not_null(cls, v: Any) -> Any:
        if v is None:
            raise ValueError("name must not be null")
        return v

    @field_validator("type", mode="before")
    @classmethod
    def type_not_null(cls, v: Any) -> Any:
        if v is None:
            raise ValueError("type must not be null")
        return v

    @field_validator("attributes", mode="before")
    @classmethod
    def validate_attributes(cls, v: Any) -> Any:
        return _check_attrs(v)


class RelationshipInput(BaseModel):
    source_id: str
    target_id: str
    type: str = Field(..., min_length=1)
    attributes: Optional[dict[str, Any]] = Field(default=None)

    @field_validator("attributes", mode="before")
    @classmethod
    def validate_attributes(cls, v: Any) -> Any:
        return _check_attrs(v)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    get_db()
    yield


app = FastAPI(title="CMDB API", version="1.0.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    details = []
    for err in exc.errors():
        details.append({
            "loc": list(err.get("loc", [])),
            "msg": err.get("msg", ""),
            "type": err.get("type", ""),
        })
    return JSONResponse(
        status_code=422,
        content={"error": "validation_error", "message": "Request validation failed", "details": details},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if isinstance(exc.detail, dict):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "http_error", "message": str(exc.detail)},
    )


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
def health_check():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# CI endpoints
# ---------------------------------------------------------------------------

@app.post("/cis", status_code=201)
def create_ci(ci_in: CIInput):
    db = get_db()
    ci_id = new_uuid()
    ts = now_iso()
    attrs = ci_in.attributes if ci_in.attributes is not None else {}
    attrs_json = json.dumps(attrs)

    db.execute(
        "INSERT INTO cis (id, name, type, attributes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (ci_id, ci_in.name, ci_in.type, attrs_json, ts, ts),
    )
    db.commit()

    return {
        "id": ci_id,
        "name": ci_in.name,
        "type": ci_in.type,
        "attributes": attrs,
        "created_at": ts,
        "updated_at": ts,
    }


@app.get("/cis")
def list_cis(
    type: Optional[str] = Query(default=None),
    name: Optional[str] = Query(default=None),
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
):
    db = get_db()
    conditions: list[str] = []
    params: list[Any] = []

    if type is not None:
        conditions.append("type = ?")
        params.append(type)
    if name is not None:
        conditions.append("name = ?")
        params.append(name)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    total = db.execute(f"SELECT COUNT(*) FROM cis {where}", params).fetchone()[0]
    rows = db.execute(
        f"SELECT * FROM cis {where} ORDER BY created_at ASC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()

    return {"items": [ci_row_to_dict(r) for r in rows], "total": total}


@app.get("/cis/{ci_id}")
def get_ci(ci_id: str):
    db = get_db()
    row = db.execute("SELECT * FROM cis WHERE id = ?", (ci_id,)).fetchone()
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": f"CI '{ci_id}' not found"},
        )
    return ci_row_to_dict(row)


@app.put("/cis/{ci_id}")
def update_ci(ci_id: str, ci_in: CIInput):
    db = get_db()
    row = db.execute("SELECT * FROM cis WHERE id = ?", (ci_id,)).fetchone()
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": f"CI '{ci_id}' not found"},
        )

    ts = now_iso()
    attrs = ci_in.attributes if ci_in.attributes is not None else {}
    attrs_json = json.dumps(attrs)

    db.execute(
        "UPDATE cis SET name = ?, type = ?, attributes = ?, updated_at = ? WHERE id = ?",
        (ci_in.name, ci_in.type, attrs_json, ts, ci_id),
    )
    db.commit()

    return {
        "id": ci_id,
        "name": ci_in.name,
        "type": ci_in.type,
        "attributes": attrs,
        "created_at": row["created_at"],
        "updated_at": ts,
    }


@app.delete("/cis/{ci_id}", status_code=204)
def delete_ci(ci_id: str):
    db = get_db()
    row = db.execute("SELECT id FROM cis WHERE id = ?", (ci_id,)).fetchone()
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": f"CI '{ci_id}' not found"},
        )

    rel_count = db.execute(
        "SELECT COUNT(*) FROM relationships WHERE source_id = ? OR target_id = ?",
        (ci_id, ci_id),
    ).fetchone()[0]

    if rel_count > 0:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "conflict",
                "message": f"CI '{ci_id}' has {rel_count} active relationship(s) and cannot be deleted",
            },
        )

    db.execute("DELETE FROM cis WHERE id = ?", (ci_id,))
    db.commit()
    return None


# ---------------------------------------------------------------------------
# Relationship endpoints
# ---------------------------------------------------------------------------

@app.post("/relationships", status_code=201)
def create_relationship(rel_in: RelationshipInput):
    db = get_db()

    src = db.execute("SELECT id FROM cis WHERE id = ?", (rel_in.source_id,)).fetchone()
    if not src:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": f"Source CI '{rel_in.source_id}' not found"},
        )

    tgt = db.execute("SELECT id FROM cis WHERE id = ?", (rel_in.target_id,)).fetchone()
    if not tgt:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": f"Target CI '{rel_in.target_id}' not found"},
        )

    rel_id = new_uuid()
    ts = now_iso()
    attrs = rel_in.attributes if rel_in.attributes is not None else {}
    attrs_json = json.dumps(attrs)

    db.execute(
        "INSERT INTO relationships (id, source_id, target_id, type, attributes, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (rel_id, rel_in.source_id, rel_in.target_id, rel_in.type, attrs_json, ts),
    )
    db.commit()

    return {
        "id": rel_id,
        "source_id": rel_in.source_id,
        "target_id": rel_in.target_id,
        "type": rel_in.type,
        "attributes": attrs,
        "created_at": ts,
    }


@app.get("/relationships/{rel_id}")
def get_relationship(rel_id: str):
    db = get_db()
    row = db.execute("SELECT * FROM relationships WHERE id = ?", (rel_id,)).fetchone()
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": f"Relationship '{rel_id}' not found"},
        )
    return rel_row_to_dict(row)


@app.delete("/relationships/{rel_id}", status_code=204)
def delete_relationship(rel_id: str):
    db = get_db()
    row = db.execute("SELECT id FROM relationships WHERE id = ?", (rel_id,)).fetchone()
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": f"Relationship '{rel_id}' not found"},
        )
    db.execute("DELETE FROM relationships WHERE id = ?", (rel_id,))
    db.commit()
    return None


@app.get("/cis/{ci_id}/relationships")
def get_ci_relationships(
    ci_id: str,
    direction: str = Query(default="both"),
    type: Optional[str] = Query(default=None),
):
    if direction not in ("inbound", "outbound", "both"):
        raise HTTPException(
            status_code=422,
            detail={"error": "validation_error", "message": "direction must be inbound, outbound, or both"},
        )

    db = get_db()
    row = db.execute("SELECT id FROM cis WHERE id = ?", (ci_id,)).fetchone()
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": f"CI '{ci_id}' not found"},
        )

    conditions: list[str] = []
    params: list[Any] = []

    if direction == "outbound":
        conditions.append("source_id = ?")
        params.append(ci_id)
    elif direction == "inbound":
        conditions.append("target_id = ?")
        params.append(ci_id)
    else:
        conditions.append("(source_id = ? OR target_id = ?)")
        params.extend([ci_id, ci_id])

    if type is not None:
        conditions.append("type = ?")
        params.append(type)

    where = "WHERE " + " AND ".join(conditions)
    rows = db.execute(f"SELECT * FROM relationships {where}", params).fetchall()

    return {"items": [rel_row_to_dict(r) for r in rows]}


# ---------------------------------------------------------------------------
# Stub / extended endpoints (referenced by client but not in core test suite)
# ---------------------------------------------------------------------------

@app.post("/cis/bulk", status_code=201)
async def bulk_create_cis(request: Request):
    body = await request.json()
    items = body.get("items", [])
    db = get_db()
    created = []
    for item in items:
        ci_id = new_uuid()
        ts = now_iso()
        name = item.get("name", "")
        ci_type = item.get("type", "")
        attrs = item.get("attributes") or {}
        db.execute(
            "INSERT INTO cis (id, name, type, attributes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (ci_id, name, ci_type, json.dumps(attrs), ts, ts),
        )
        created.append({"id": ci_id, "name": name, "type": ci_type, "attributes": attrs, "created_at": ts, "updated_at": ts})
    db.commit()
    return {"items": created}


@app.get("/cis/{ci_id}/history")
def get_ci_history(ci_id: str):
    db = get_db()
    row = db.execute("SELECT id FROM cis WHERE id = ?", (ci_id,)).fetchone()
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": f"CI '{ci_id}' not found"},
        )
    return {"items": []}


@app.get("/cis/{ci_id}/impact")
def get_ci_impact(
    ci_id: str,
    depth: int = Query(default=3, ge=0),
    relationship_types: Optional[str] = Query(default=None),
):
    db = get_db()
    row = db.execute("SELECT id FROM cis WHERE id = ?", (ci_id,)).fetchone()
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": f"CI '{ci_id}' not found"},
        )

    rel_types = [t.strip() for t in relationship_types.split(",")] if relationship_types else None
    visited: set[str] = {ci_id}
    frontier: set[str] = {ci_id}

    for _ in range(depth):
        if not frontier:
            break
        placeholders = ",".join("?" * len(frontier))
        params: list[Any] = list(frontier)
        q = f"SELECT target_id FROM relationships WHERE source_id IN ({placeholders})"
        if rel_types:
            q += f" AND type IN ({','.join('?' * len(rel_types))})"
            params += rel_types
        rows = db.execute(q, params).fetchall()
        new_frontier: set[str] = set()
        for r in rows:
            tgt = r["target_id"]
            if tgt not in visited:
                visited.add(tgt)
                new_frontier.add(tgt)
        frontier = new_frontier

    result_ids = visited - {ci_id}
    items = []
    for rid in result_ids:
        ci_row = db.execute("SELECT * FROM cis WHERE id = ?", (rid,)).fetchone()
        if ci_row:
            items.append(ci_row_to_dict(ci_row))
    return {"items": items}


@app.get("/cis/{ci_id}/dependencies")
def get_ci_dependencies(
    ci_id: str,
    depth: int = Query(default=3, ge=0),
    relationship_types: Optional[str] = Query(default=None),
):
    db = get_db()
    row = db.execute("SELECT id FROM cis WHERE id = ?", (ci_id,)).fetchone()
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": f"CI '{ci_id}' not found"},
        )

    rel_types = [t.strip() for t in relationship_types.split(",")] if relationship_types else None
    visited: set[str] = {ci_id}
    frontier: set[str] = {ci_id}

    for _ in range(depth):
        if not frontier:
            break
        placeholders = ",".join("?" * len(frontier))
        params: list[Any] = list(frontier)
        q = f"SELECT source_id FROM relationships WHERE target_id IN ({placeholders})"
        if rel_types:
            q += f" AND type IN ({','.join('?' * len(rel_types))})"
            params += rel_types
        rows = db.execute(q, params).fetchall()
        new_frontier: set[str] = set()
        for r in rows:
            src = r["source_id"]
            if src not in visited:
                visited.add(src)
                new_frontier.add(src)
        frontier = new_frontier

    result_ids = visited - {ci_id}
    items = []
    for rid in result_ids:
        ci_row = db.execute("SELECT * FROM cis WHERE id = ?", (rid,)).fetchone()
        if ci_row:
            items.append(ci_row_to_dict(ci_row))
    return {"items": items}


@app.post("/policies", status_code=201)
async def create_policy(request: Request):
    body = await request.json()
    return {
        "id": new_uuid(),
        "ci_type": body.get("ci_type", ""),
        "rules": body.get("rules", {}),
        "created_at": now_iso(),
    }


@app.get("/policies")
def list_policies():
    return {"items": []}


@app.delete("/policies/{policy_id}", status_code=204)
def delete_policy(policy_id: str):
    return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=9090, reload=False)