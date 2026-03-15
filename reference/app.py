"""CMDB API Server — FastAPI + SQLite (in-process).

Listens on 0.0.0.0:9090. Entry point: python app.py
"""
from __future__ import annotations

import fnmatch
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

DB_PATH = "cmdb.db"


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db():
    conn = make_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cis (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                attributes TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS relationships (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                type TEXT NOT NULL,
                attributes TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id TEXT PRIMARY KEY,
                ci_id TEXT NOT NULL,
                action TEXT NOT NULL,
                changes TEXT NOT NULL DEFAULT '{}',
                snapshot TEXT NOT NULL DEFAULT '{}',
                timestamp TEXT NOT NULL,
                actor TEXT NOT NULL DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS policies (
                id TEXT PRIMARY KEY,
                ci_type TEXT NOT NULL,
                rules TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
        """)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_uuid() -> str:
    return str(uuid.uuid4())


def sanitize_str(value: str) -> str:
    """Remove null bytes and other problematic characters from strings."""
    if isinstance(value, str):
        # Remove null bytes which cause SQLite issues
        return value.replace('\x00', '')
    return value


def sanitize_string_value(v: Any) -> Any:
    """Sanitize a value that might be a string."""
    if isinstance(v, str):
        return sanitize_str(v)
    return v


def ci_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "type": row["type"],
        "attributes": json.loads(row["attributes"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def rel_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "source_id": row["source_id"],
        "target_id": row["target_id"],
        "type": row["type"],
        "attributes": json.loads(row["attributes"]),
        "created_at": row["created_at"],
    }


def _add_audit(
    conn: sqlite3.Connection,
    ci_id: str,
    action: str,
    changes: dict | None = None,
    snapshot: dict | None = None,
    timestamp: str | None = None,
):
    conn.execute(
        "INSERT INTO audit_log (id, ci_id, action, changes, snapshot, timestamp, actor) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            new_uuid(), ci_id, action,
            json.dumps(changes or {}),
            json.dumps(snapshot or {}),
            timestamp or now_iso(), "",
        ),
    )


def _enforce_policies(conn: sqlite3.Connection, ci_type: str, attrs: dict):
    """Check all active policies for this CI type. Raise HTTPException on violation."""
    rows = conn.execute(
        "SELECT rules FROM policies WHERE ci_type=?", (ci_type,)
    ).fetchall()
    for row in rows:
        rules = json.loads(row["rules"])

        # required_attributes
        for req_attr in rules.get("required_attributes", []):
            if req_attr not in attrs or attrs[req_attr] is None:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": "PolicyViolation",
                        "message": f"Policy requires attribute '{req_attr}' for type '{ci_type}'",
                    },
                )

        # allowed_values
        for attr_name, allowed in rules.get("allowed_values", {}).items():
            if attr_name in attrs and attrs[attr_name] not in allowed:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": "PolicyViolation",
                        "message": (
                            f"Attribute '{attr_name}' value '{attrs[attr_name]}' "
                            f"not in allowed values {allowed} for type '{ci_type}'"
                        ),
                    },
                )


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CIInput(BaseModel):
    name: str
    type: str
    attributes: Optional[dict[str, Any]] = None

    @field_validator("name", mode="before")
    @classmethod
    def name_not_empty(cls, v: Any) -> str:
        if v is None:
            raise ValueError("name is required and must not be null")
        if not isinstance(v, str):
            raise ValueError("name must be a string")
        # Remove null bytes
        v = v.replace('\x00', '')
        if len(v) == 0:
            raise ValueError("name must not be empty")
        return v

    @field_validator("type", mode="before")
    @classmethod
    def type_not_empty(cls, v: Any) -> str:
        if v is None:
            raise ValueError("type is required and must not be null")
        if not isinstance(v, str):
            raise ValueError("type must be a string")
        # Remove null bytes
        v = v.replace('\x00', '')
        if len(v) == 0:
            raise ValueError("type must not be empty")
        return v

    @field_validator("attributes", mode="before")
    @classmethod
    def validate_attrs(cls, v: Any) -> Any:
        if v is None:
            return v
        if not isinstance(v, dict):
            raise ValueError("attributes must be a flat object")
        sanitized = {}
        for key, value in v.items():
            if value is not None and not isinstance(value, (str, int, float, bool)):
                raise ValueError(
                    f"Attribute '{key}' has a non-scalar value "
                    "(nested objects and arrays are not permitted)"
                )
            # Sanitize string keys and values
            clean_key = key.replace('\x00', '') if isinstance(key, str) else key
            clean_value = value.replace('\x00', '') if isinstance(value, str) else value
            sanitized[clean_key] = clean_value
        return sanitized


class RelationshipInput(BaseModel):
    source_id: str
    target_id: str
    type: str
    attributes: Optional[dict[str, Any]] = None

    @field_validator("type", mode="before")
    @classmethod
    def type_not_empty(cls, v: Any) -> str:
        if v is None:
            raise ValueError("type is required")
        if not isinstance(v, str):
            raise ValueError("type must be a string")
        v = v.replace('\x00', '')
        if len(v) == 0:
            raise ValueError("type must not be empty")
        return v

    @field_validator("source_id", "target_id", mode="before")
    @classmethod
    def sanitize_ids(cls, v: Any) -> str:
        if isinstance(v, str):
            return v.replace('\x00', '')
        return v

    @field_validator("attributes", mode="before")
    @classmethod
    def validate_attrs(cls, v: Any) -> Any:
        if v is None:
            return v
        if not isinstance(v, dict):
            raise ValueError("attributes must be a flat object")
        sanitized = {}
        for key, value in v.items():
            if value is not None and not isinstance(value, (str, int, float, bool)):
                raise ValueError(
                    f"Attribute '{key}' has a non-scalar value "
                    "(nested objects and arrays are not permitted)"
                )
            clean_key = key.replace('\x00', '') if isinstance(key, str) else key
            clean_value = value.replace('\x00', '') if isinstance(value, str) else value
            sanitized[clean_key] = clean_value
        return sanitized


class BulkCIInput(BaseModel):
    items: list[CIInput]


class PolicyInput(BaseModel):
    ci_type: str
    rules: dict[str, Any]

    @field_validator("ci_type", mode="before")
    @classmethod
    def sanitize_ci_type(cls, v: Any) -> str:
        if isinstance(v, str):
            return v.replace('\x00', '')
        return v


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(title="CMDB API", version="1.0.0")


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
        content={
            "error": "ValidationError",
            "message": "Request validation failed",
            "details": details,
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if isinstance(exc.detail, dict):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "HTTPError", "message": str(exc.detail)},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": "InternalServerError", "message": str(exc)},
    )


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
def health_check():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# CIs — bulk must come BEFORE parameterised routes
# ---------------------------------------------------------------------------

@app.post("/cis/bulk", status_code=201)
def bulk_create_cis(body: BulkCIInput):
    created = []
    with db() as conn:
        for item in body.items:
            ci_id = new_uuid()
            ts = now_iso()
            attrs = item.attributes or {}
            conn.execute(
                "INSERT INTO cis (id, name, type, attributes, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?)",
                (ci_id, item.name, item.type, json.dumps(attrs), ts, ts),
            )
            ci_dict = {
                "id": ci_id,
                "name": item.name,
                "type": item.type,
                "attributes": attrs,
                "created_at": ts,
                "updated_at": ts,
            }
            _add_audit(conn, ci_id, "created", {"name": item.name, "type": item.type}, snapshot=ci_dict)
            created.append(ci_dict)
    return {"items": created}


@app.post("/cis", status_code=201)
def create_ci(body: CIInput):
    ci_id = new_uuid()
    ts = now_iso()
    attrs = body.attributes or {}

    with db() as conn:
        _enforce_policies(conn, body.type, attrs)
        conn.execute(
            "INSERT INTO cis (id, name, type, attributes, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (ci_id, body.name, body.type, json.dumps(attrs), ts, ts),
        )
        ci_dict = {
            "id": ci_id, "name": body.name, "type": body.type,
            "attributes": attrs, "created_at": ts, "updated_at": ts,
        }
        _add_audit(conn, ci_id, "created", {"name": body.name, "type": body.type}, snapshot=ci_dict, timestamp=ts)

    return ci_dict


@app.get("/cis")
def list_cis(
    type: Optional[str] = Query(default=None),
    name: Optional[str] = Query(default=None),
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0),
):
    with db() as conn:
        conditions: list[str] = []
        params: list[Any] = []

        if type is not None:
            conditions.append("type = ?")
            params.append(type)
        if name is not None:
            conditions.append("name = ?")
            params.append(name)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        total = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM cis {where}", params
        ).fetchone()["cnt"]

        rows = conn.execute(
            f"SELECT * FROM cis {where} ORDER BY created_at ASC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

    return {"items": [ci_row_to_dict(r) for r in rows], "total": total}


# ---------------------------------------------------------------------------
# Search (must be before /cis/{id} parameterized routes)
# ---------------------------------------------------------------------------

@app.get("/cis/search")
def search_cis(request: Request):
    params = dict(request.query_params)
    q = params.pop("q", None)
    name_filter = params.pop("name", None)
    type_filter = params.pop("type", None)
    sort_param = params.pop("sort", None)
    limit = int(params.pop("limit", "100"))
    offset = int(params.pop("offset", "0"))

    # Remaining params are attribute filters (attributes.key=value)
    attr_filters: dict[str, str] = {}
    for key, value in params.items():
        if key.startswith("attributes."):
            attr_name = key[len("attributes."):]
            attr_filters[attr_name] = value

    with db() as conn:
        rows = conn.execute("SELECT * FROM cis").fetchall()

    results = []
    for row in rows:
        ci = ci_row_to_dict(row)
        attrs = ci["attributes"]

        # Type filter
        if type_filter and ci["type"] != type_filter:
            continue

        # Name wildcard filter
        if name_filter:
            if not fnmatch.fnmatch(ci["name"], name_filter):
                continue

        # Attribute filters (all must match)
        if attr_filters:
            match = True
            for ak, av in attr_filters.items():
                if str(attrs.get(ak, "")) != av:
                    match = False
                    break
            if not match:
                continue

        # Full-text search (q)
        if q is not None and q != "":
            q_lower = q.lower()
            searchable = (
                ci["name"].lower()
                + " " + ci["type"].lower()
                + " " + " ".join(str(v).lower() for v in attrs.values())
            )
            if q_lower not in searchable:
                continue

        results.append(ci)

    # Sorting
    if sort_param:
        parts = sort_param.split(":")
        field = parts[0]
        direction = parts[1] if len(parts) > 1 else "asc"
        reverse = direction == "desc"
        results.sort(key=lambda c: c.get(field, ""), reverse=reverse)

    # Pagination
    total = len(results)
    results = results[offset:offset + limit]

    return {"items": results, "total": total}


@app.get("/cis/{id}/history")
def get_ci_history(id: str):
    with db() as conn:
        # Check audit_log — history must survive CI deletion
        logs = conn.execute(
            "SELECT * FROM audit_log WHERE ci_id=? ORDER BY timestamp ASC", (id,)
        ).fetchall()

        if not logs:
            # No history at all means this CI never existed
            raise HTTPException(
                status_code=404,
                detail={"error": "NotFound", "message": f"CI '{id}' not found"},
            )

    items = [
        {
            "id": log["id"],
            "ci_id": log["ci_id"],
            "action": log["action"],
            "changes": json.loads(log["changes"]),
            "timestamp": log["timestamp"],
            "actor": log["actor"],
        }
        for log in logs
    ]
    return {"items": items}


@app.get("/cis/{id}/history/{entry_id}/diff")
def get_ci_diff(id: str, entry_id: str):
    with db() as conn:
        entry = conn.execute(
            "SELECT * FROM audit_log WHERE id=? AND ci_id=?", (entry_id, id),
        ).fetchone()
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "NotFound", "message": f"Audit entry '{entry_id}' not found"},
        )

    changes_raw = json.loads(entry["changes"])
    # changes could be a list of {field, old_value, new_value} or a dict (legacy)
    if isinstance(changes_raw, list):
        changes = changes_raw
    else:
        # Legacy format: convert dict to list
        changes = [
            {"field": k, "old_value": None, "new_value": v}
            for k, v in changes_raw.items()
        ]

    return {
        "action": entry["action"],
        "timestamp": entry["timestamp"],
        "changes": changes,
    }


@app.get("/cis/{id}/history/{entry_id}/snapshot")
def get_ci_snapshot(id: str, entry_id: str):
    with db() as conn:
        entry = conn.execute(
            "SELECT * FROM audit_log WHERE id=? AND ci_id=?", (entry_id, id),
        ).fetchone()
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "NotFound", "message": f"Audit entry '{entry_id}' not found"},
        )
    snapshot = json.loads(entry["snapshot"])
    return snapshot


@app.get("/cis/{id}/diff")
def get_ci_diff_range(
    id: str,
    request: Request,
):
    params = dict(request.query_params)
    from_ts = params.get("from", "")
    to_ts = params.get("to", "")

    with db() as conn:
        entries = conn.execute(
            "SELECT * FROM audit_log WHERE ci_id=? AND action='updated' "
            "AND timestamp > ? AND timestamp <= ? ORDER BY timestamp ASC",
            (id, from_ts, to_ts),
        ).fetchall()

    changes = []
    for entry in entries:
        changes_raw = json.loads(entry["changes"])
        if isinstance(changes_raw, list):
            changes.extend(changes_raw)

    return {"changes": changes}


@app.get("/cis/{id}/impact")
def get_ci_impact(
    id: str,
    depth: int = Query(default=3),
    relationship_types: Optional[str] = Query(default=None),
):
    with db() as conn:
        row = conn.execute("SELECT id FROM cis WHERE id=?", (id,)).fetchone()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "NotFound", "message": f"CI '{id}' not found"},
            )

        rel_types = [t.strip() for t in relationship_types.split(",")] if relationship_types else None

        # BFS
        visited: set[str] = {id}
        queue: list[tuple[str, int]] = [(id, 0)]
        result_ids: list[str] = []

        while queue:
            current_id, current_depth = queue.pop(0)
            if current_depth >= depth:
                continue

            if rel_types:
                placeholders = ",".join("?" * len(rel_types))
                rels = conn.execute(
                    f"SELECT target_id FROM relationships "
                    f"WHERE source_id=? AND type IN ({placeholders})",
                    [current_id] + rel_types,
                ).fetchall()
            else:
                rels = conn.execute(
                    "SELECT target_id FROM relationships WHERE source_id=?",
                    (current_id,),
                ).fetchall()

            for rel in rels:
                target = rel["target_id"]
                if target not in visited:
                    visited.add(target)
                    result_ids.append(target)
                    queue.append((target, current_depth + 1))

        items = []
        for ci_id in result_ids:
            r = conn.execute("SELECT * FROM cis WHERE id=?", (ci_id,)).fetchone()
            if r:
                items.append(ci_row_to_dict(r))

    return {"items": items}


@app.get("/cis/{id}/dependencies")
def get_ci_dependencies(
    id: str,
    depth: int = Query(default=3),
    relationship_types: Optional[str] = Query(default=None),
):
    with db() as conn:
        row = conn.execute("SELECT id FROM cis WHERE id=?", (id,)).fetchone()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "NotFound", "message": f"CI '{id}' not found"},
            )

        rel_types = [t.strip() for t in relationship_types.split(",")] if relationship_types else None

        # BFS
        visited: set[str] = {id}
        queue: list[tuple[str, int]] = [(id, 0)]
        result_ids: list[str] = []

        while queue:
            current_id, current_depth = queue.pop(0)
            if current_depth >= depth:
                continue

            if rel_types:
                placeholders = ",".join("?" * len(rel_types))
                rels = conn.execute(
                    f"SELECT source_id FROM relationships "
                    f"WHERE target_id=? AND type IN ({placeholders})",
                    [current_id] + rel_types,
                ).fetchall()
            else:
                rels = conn.execute(
                    "SELECT source_id FROM relationships WHERE target_id=?",
                    (current_id,),
                ).fetchall()

            for rel in rels:
                source = rel["source_id"]
                if source not in visited:
                    visited.add(source)
                    result_ids.append(source)
                    queue.append((source, current_depth + 1))

        items = []
        for ci_id in result_ids:
            r = conn.execute("SELECT * FROM cis WHERE id=?", (ci_id,)).fetchone()
            if r:
                items.append(ci_row_to_dict(r))

    return {"items": items}


@app.get("/cis/{id}/relationships")
def get_ci_relationships(
    id: str,
    direction: str = Query(default="both"),
    type: Optional[str] = Query(default=None),
):
    with db() as conn:
        row = conn.execute("SELECT id FROM cis WHERE id=?", (id,)).fetchone()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "NotFound", "message": f"CI '{id}' not found"},
            )

        conditions: list[str] = []
        params: list[Any] = []

        if direction == "outbound":
            conditions.append("source_id = ?")
            params.append(id)
        elif direction == "inbound":
            conditions.append("target_id = ?")
            params.append(id)
        else:  # both
            conditions.append("(source_id = ? OR target_id = ?)")
            params.extend([id, id])

        if type is not None:
            conditions.append("type = ?")
            params.append(type)

        where = "WHERE " + " AND ".join(conditions)
        rows = conn.execute(
            f"SELECT * FROM relationships {where} ORDER BY created_at ASC", params
        ).fetchall()

    return {"items": [rel_row_to_dict(r) for r in rows]}


@app.get("/cis/{id}")
def get_ci(id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM cis WHERE id=?", (id,)).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "NotFound", "message": f"CI '{id}' not found"},
        )
    return ci_row_to_dict(row)


@app.put("/cis/{id}")
def update_ci(id: str, body: CIInput):
    ts = now_iso()
    attrs = body.attributes if body.attributes is not None else {}

    with db() as conn:
        row = conn.execute("SELECT * FROM cis WHERE id=?", (id,)).fetchone()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "NotFound", "message": f"CI '{id}' not found"},
            )
        _enforce_policies(conn, body.type, attrs)
        created_at = row["created_at"]
        old_name = row["name"]
        old_type = row["type"]
        old_attrs = json.loads(row["attributes"])

        conn.execute(
            "UPDATE cis SET name=?, type=?, attributes=?, updated_at=? WHERE id=?",
            (body.name, body.type, json.dumps(attrs), ts, id),
        )

        # Compute attribute-level changes
        changes = []
        if old_name != body.name:
            changes.append({"field": "name", "old_value": old_name, "new_value": body.name})
        if old_type != body.type:
            changes.append({"field": "type", "old_value": old_type, "new_value": body.type})
        # Attribute changes
        all_attr_keys = set(list(old_attrs.keys()) + list(attrs.keys()))
        for key in sorted(all_attr_keys):
            old_val = old_attrs.get(key)
            new_val = attrs.get(key)
            if old_val != new_val:
                changes.append({
                    "field": f"attributes.{key}",
                    "old_value": old_val,
                    "new_value": new_val,
                })

        ci_dict = {
            "id": id, "name": body.name, "type": body.type,
            "attributes": attrs, "created_at": created_at, "updated_at": ts,
        }
        _add_audit(conn, id, "updated", changes, snapshot=ci_dict, timestamp=ts)

    return ci_dict


@app.delete("/cis/{id}", status_code=204)
def delete_ci(id: str):
    with db() as conn:
        row = conn.execute("SELECT id FROM cis WHERE id=?", (id,)).fetchone()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "NotFound", "message": f"CI '{id}' not found"},
            )
        rel_count = conn.execute(
            "SELECT COUNT(*) AS cnt FROM relationships WHERE source_id=? OR target_id=?",
            (id, id),
        ).fetchone()["cnt"]
        if rel_count > 0:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "Conflict",
                    "message": (
                        f"CI '{id}' has {rel_count} active relationship(s) "
                        "and cannot be deleted"
                    ),
                },
            )
        # Grab full CI before deleting for audit snapshot
        full_row = conn.execute("SELECT * FROM cis WHERE id=?", (id,)).fetchone()
        delete_snapshot = ci_row_to_dict(full_row) if full_row else {}
        conn.execute("DELETE FROM cis WHERE id=?", (id,))
        _add_audit(conn, id, "deleted", {}, snapshot=delete_snapshot)
    return None


# ---------------------------------------------------------------------------
# Relationships
# ---------------------------------------------------------------------------

@app.post("/relationships", status_code=201)
def create_relationship(body: RelationshipInput):
    rel_id = new_uuid()
    ts = now_iso()
    attrs = body.attributes or {}

    with db() as conn:
        src = conn.execute("SELECT id FROM cis WHERE id=?", (body.source_id,)).fetchone()
        if src is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "NotFound",
                    "message": f"Source CI '{body.source_id}' not found",
                },
            )
        tgt = conn.execute("SELECT id FROM cis WHERE id=?", (body.target_id,)).fetchone()
        if tgt is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "NotFound",
                    "message": f"Target CI '{body.target_id}' not found",
                },
            )
        conn.execute(
            "INSERT INTO relationships (id, source_id, target_id, type, attributes, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (rel_id, body.source_id, body.target_id, body.type, json.dumps(attrs), ts),
        )

    return {
        "id": rel_id,
        "source_id": body.source_id,
        "target_id": body.target_id,
        "type": body.type,
        "attributes": attrs,
        "created_at": ts,
    }


@app.get("/relationships/{id}")
def get_relationship(id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM relationships WHERE id=?", (id,)).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "NotFound", "message": f"Relationship '{id}' not found"},
        )
    return rel_row_to_dict(row)


@app.delete("/relationships/{id}", status_code=204)
def delete_relationship(id: str):
    with db() as conn:
        row = conn.execute("SELECT id FROM relationships WHERE id=?", (id,)).fetchone()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "NotFound", "message": f"Relationship '{id}' not found"},
            )
        conn.execute("DELETE FROM relationships WHERE id=?", (id,))
    return None


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------

@app.post("/policies", status_code=201)
def create_policy(body: PolicyInput):
    policy_id = new_uuid()
    ts = now_iso()
    with db() as conn:
        conn.execute(
            "INSERT INTO policies (id, ci_type, rules, created_at) VALUES (?,?,?,?)",
            (policy_id, body.ci_type, json.dumps(body.rules), ts),
        )
    return {
        "id": policy_id,
        "ci_type": body.ci_type,
        "rules": body.rules,
        "created_at": ts,
    }


@app.get("/policies")
def list_policies():
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM policies ORDER BY created_at ASC"
        ).fetchall()
    return {
        "items": [
            {
                "id": row["id"],
                "ci_type": row["ci_type"],
                "rules": json.loads(row["rules"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
    }


@app.delete("/policies/{id}", status_code=204)
def delete_policy(id: str):
    with db() as conn:
        row = conn.execute("SELECT id FROM policies WHERE id=?", (id,)).fetchone()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "NotFound", "message": f"Policy '{id}' not found"},
            )
        conn.execute("DELETE FROM policies WHERE id=?", (id,))
    return None


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

class ReconcileItem(BaseModel):
    name: str
    type: str
    attributes: Optional[dict[str, Any]] = None


class ReconcileInput(BaseModel):
    source: str
    items: list[ReconcileItem]
    apply: bool = False

    @field_validator("source", mode="before")
    @classmethod
    def source_not_empty(cls, v: Any) -> str:
        if v is None or (isinstance(v, str) and len(v) == 0):
            raise ValueError("source is required")
        return v


@app.post("/cis/reconcile")
def reconcile_cis(body: ReconcileInput):
    source = body.source
    items = body.items
    apply = body.apply

    with db() as conn:
        # Find all existing CIs with this source
        all_cis = conn.execute("SELECT * FROM cis").fetchall()
        existing_by_name: dict[str, dict] = {}
        for row in all_cis:
            ci = ci_row_to_dict(row)
            if ci["attributes"].get("source") == source:
                existing_by_name[ci["name"]] = ci

        new_items: list[dict] = []
        updated_items: list[dict] = []
        unchanged_items: list[dict] = []
        seen_names: set[str] = set()

        for item in items:
            seen_names.add(item.name)
            item_attrs = item.attributes or {}

            if item.name in existing_by_name:
                existing = existing_by_name[item.name]
                existing_attrs = dict(existing["attributes"])
                # Remove 'source' from comparison
                existing_compare = {k: v for k, v in existing_attrs.items() if k != "source"}

                if existing_compare == item_attrs and existing["type"] == item.type:
                    unchanged_items.append({
                        "id": existing["id"],
                        "name": existing["name"],
                        "type": existing["type"],
                    })
                else:
                    updated_items.append({
                        "id": existing["id"],
                        "name": existing["name"],
                        "type": item.type,
                    })
                    if apply:
                        new_attrs = dict(item_attrs)
                        new_attrs["source"] = source
                        ts = now_iso()
                        old_attrs = json.loads(
                            conn.execute("SELECT attributes FROM cis WHERE id=?", (existing["id"],)).fetchone()["attributes"]
                        )
                        conn.execute(
                            "UPDATE cis SET name=?, type=?, attributes=?, updated_at=? WHERE id=?",
                            (item.name, item.type, json.dumps(new_attrs), ts, existing["id"]),
                        )
                        # Compute changes for audit
                        changes = []
                        all_keys = set(list(old_attrs.keys()) + list(new_attrs.keys()))
                        for key in sorted(all_keys):
                            ov = old_attrs.get(key)
                            nv = new_attrs.get(key)
                            if ov != nv:
                                changes.append({"field": f"attributes.{key}", "old_value": ov, "new_value": nv})
                        ci_dict = {
                            "id": existing["id"], "name": item.name, "type": item.type,
                            "attributes": new_attrs, "created_at": existing["created_at"], "updated_at": ts,
                        }
                        _add_audit(conn, existing["id"], "updated", changes, snapshot=ci_dict)
            else:
                if apply:
                    ci_id = new_uuid()
                    ts = now_iso()
                    new_attrs = dict(item_attrs)
                    new_attrs["source"] = source
                    conn.execute(
                        "INSERT INTO cis (id, name, type, attributes, created_at, updated_at) "
                        "VALUES (?,?,?,?,?,?)",
                        (ci_id, item.name, item.type, json.dumps(new_attrs), ts, ts),
                    )
                    ci_dict = {
                        "id": ci_id, "name": item.name, "type": item.type,
                        "attributes": new_attrs, "created_at": ts, "updated_at": ts,
                    }
                    _add_audit(conn, ci_id, "created", {"name": item.name, "type": item.type}, snapshot=ci_dict)
                    new_items.append({
                        "id": ci_id,
                        "name": item.name,
                        "type": item.type,
                    })
                else:
                    new_items.append({
                        "name": item.name,
                        "type": item.type,
                    })

        # Stale: existing CIs from this source that weren't in the input
        stale_items: list[dict] = []
        for name, ci in existing_by_name.items():
            if name not in seen_names:
                stale_items.append({
                    "id": ci["id"],
                    "name": ci["name"],
                    "type": ci["type"],
                })

    return {
        "new": new_items,
        "updated": updated_items,
        "unchanged": unchanged_items,
        "stale": stale_items,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    import os
    port = int(os.environ.get("PORT", "9090"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")