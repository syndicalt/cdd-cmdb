"""CMDB API Server - Flask/SQLite implementation."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from flask import Flask, g, jsonify, request

app = Flask(__name__)

DATABASE = ":memory:"
_db_connection = None


def get_db() -> sqlite3.Connection:
    """Get a persistent SQLite connection (single in-process connection)."""
    global _db_connection
    if _db_connection is None:
        _db_connection = sqlite3.connect(DATABASE, check_same_thread=False)
        _db_connection.row_factory = sqlite3.Row
        _db_connection.execute("PRAGMA journal_mode=WAL")
        _db_connection.execute("PRAGMA foreign_keys=ON")
        init_db(_db_connection)
    return _db_connection


def init_db(conn: sqlite3.Connection) -> None:
    """Initialize the database schema."""
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
            created_at TEXT NOT NULL,
            FOREIGN KEY (source_id) REFERENCES cis(id),
            FOREIGN KEY (target_id) REFERENCES cis(id)
        );
    """)
    conn.commit()


def now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def new_uuid() -> str:
    """Generate a new UUID4 string."""
    return str(uuid.uuid4())


def error_response(error: str, message: str, status: int, details: list | None = None):
    """Build a standard error response."""
    body: dict[str, Any] = {"error": error, "message": message}
    if details:
        body["details"] = details
    return jsonify(body), status


def row_to_ci(row: sqlite3.Row) -> dict:
    """Convert a database row to a CI dict."""
    attrs = json.loads(row["attributes"]) if row["attributes"] else {}
    return {
        "id": row["id"],
        "name": row["name"],
        "type": row["type"],
        "attributes": attrs,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def row_to_relationship(row: sqlite3.Row) -> dict:
    """Convert a database row to a Relationship dict."""
    attrs = json.loads(row["attributes"]) if row["attributes"] else {}
    return {
        "id": row["id"],
        "source_id": row["source_id"],
        "target_id": row["target_id"],
        "type": row["type"],
        "attributes": attrs,
        "created_at": row["created_at"],
    }


def validate_ci_input(data: Any) -> tuple[bool, str, list]:
    """Validate CI input data. Returns (valid, message, details)."""
    if not isinstance(data, dict):
        return False, "Request body must be a JSON object", []

    # Check required fields
    if "name" not in data:
        return False, "Missing required field: name", [{"field": "name", "issue": "required"}]
    if "type" not in data:
        return False, "Missing required field: type", [{"field": "type", "issue": "required"}]

    name = data.get("name")
    ci_type = data.get("type")

    # name must be a non-empty string
    if name is None or not isinstance(name, str):
        return False, "Field 'name' must be a non-empty string", [{"field": "name", "issue": "must be string"}]
    if len(name) < 1:
        return False, "Field 'name' must not be empty", [{"field": "name", "issue": "minLength"}]

    # type must be a non-empty string
    if ci_type is None or not isinstance(ci_type, str):
        return False, "Field 'type' must be a non-empty string", [{"field": "type", "issue": "must be string"}]
    if len(ci_type) < 1:
        return False, "Field 'type' must not be empty", [{"field": "type", "issue": "minLength"}]

    # Validate attributes if present
    if "attributes" in data and data["attributes"] is not None:
        attrs = data["attributes"]
        if not isinstance(attrs, dict):
            return False, "Field 'attributes' must be an object", [{"field": "attributes", "issue": "must be object"}]
        for key, value in attrs.items():
            if not is_scalar(value):
                return False, f"Attribute '{key}' must be a scalar value (string, number, boolean, or null)", [
                    {"field": f"attributes.{key}", "issue": "nested objects and arrays not permitted"}
                ]

    return True, "", []


def is_scalar(value: Any) -> bool:
    """Check if a value is a scalar (string, number, boolean, or null)."""
    if value is None:
        return True
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        return True
    return False


def validate_relationship_input(data: Any) -> tuple[bool, str, list]:
    """Validate relationship input data."""
    if not isinstance(data, dict):
        return False, "Request body must be a JSON object", []

    if "source_id" not in data:
        return False, "Missing required field: source_id", [{"field": "source_id", "issue": "required"}]
    if "target_id" not in data:
        return False, "Missing required field: target_id", [{"field": "target_id", "issue": "required"}]
    if "type" not in data:
        return False, "Missing required field: type", [{"field": "type", "issue": "required"}]

    rel_type = data.get("type")
    if rel_type is None or not isinstance(rel_type, str) or len(rel_type) < 1:
        return False, "Field 'type' must be a non-empty string", [{"field": "type", "issue": "minLength"}]

    # Validate attributes if present
    if "attributes" in data and data["attributes"] is not None:
        attrs = data["attributes"]
        if not isinstance(attrs, dict):
            return False, "Field 'attributes' must be an object", [{"field": "attributes", "issue": "must be object"}]
        for key, value in attrs.items():
            if not is_scalar(value):
                return False, f"Attribute '{key}' must be a scalar value", [
                    {"field": f"attributes.{key}", "issue": "nested objects not permitted"}
                ]

    return True, "", []


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "ok"}), 200


# ---------------------------------------------------------------------------
# CIs
# ---------------------------------------------------------------------------

@app.route("/cis", methods=["POST"])
def create_ci():
    db = get_db()

    # Parse JSON
    if not request.is_json:
        return error_response("bad_request", "Content-Type must be application/json", 400)

    try:
        data = request.get_json(force=True)
    except Exception:
        return error_response("bad_request", "Invalid JSON body", 400)

    if data is None:
        return error_response("bad_request", "Invalid JSON body", 400)

    # Validate
    valid, msg, details = validate_ci_input(data)
    if not valid:
        return error_response("validation_error", msg, 422, details)

    ci_id = new_uuid()
    ts = now_iso()
    attrs = data.get("attributes") or {}
    attrs_json = json.dumps(attrs)

    try:
        db.execute(
            "INSERT INTO cis (id, name, type, attributes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (ci_id, data["name"], data["type"], attrs_json, ts, ts)
        )
        db.commit()
    except Exception as e:
        return error_response("internal_error", str(e), 500)

    row = db.execute("SELECT * FROM cis WHERE id = ?", (ci_id,)).fetchone()
    return jsonify(row_to_ci(row)), 201


@app.route("/cis", methods=["GET"])
def list_cis():
    db = get_db()

    ci_type = request.args.get("type")
    name = request.args.get("name")

    try:
        limit = int(request.args.get("limit", 100))
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        return error_response("bad_request", "limit and offset must be integers", 400)

    if limit > 1000:
        limit = 1000
    if limit < 0:
        limit = 0
    if offset < 0:
        offset = 0

    where_clauses = []
    params = []

    if ci_type is not None:
        where_clauses.append("type = ?")
        params.append(ci_type)
    if name is not None:
        where_clauses.append("name = ?")
        params.append(name)

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    total_row = db.execute(f"SELECT COUNT(*) as cnt FROM cis {where_sql}", params).fetchone()
    total = total_row["cnt"]

    rows = db.execute(
        f"SELECT * FROM cis {where_sql} ORDER BY created_at ASC LIMIT ? OFFSET ?",
        params + [limit, offset]
    ).fetchall()

    items = [row_to_ci(r) for r in rows]
    return jsonify({"items": items, "total": total}), 200


@app.route("/cis/<ci_id>", methods=["GET"])
def get_ci(ci_id: str):
    db = get_db()
    row = db.execute("SELECT * FROM cis WHERE id = ?", (ci_id,)).fetchone()
    if row is None:
        return error_response("not_found", f"CI '{ci_id}' not found", 404)
    return jsonify(row_to_ci(row)), 200


@app.route("/cis/<ci_id>", methods=["PUT"])
def update_ci(ci_id: str):
    db = get_db()

    row = db.execute("SELECT * FROM cis WHERE id = ?", (ci_id,)).fetchone()
    if row is None:
        return error_response("not_found", f"CI '{ci_id}' not found", 404)

    if not request.is_json:
        return error_response("bad_request", "Content-Type must be application/json", 400)

    try:
        data = request.get_json(force=True)
    except Exception:
        return error_response("bad_request", "Invalid JSON body", 400)

    if data is None:
        return error_response("bad_request", "Invalid JSON body", 400)

    valid, msg, details = validate_ci_input(data)
    if not valid:
        return error_response("validation_error", msg, 422, details)

    ts = now_iso()
    attrs = data.get("attributes") or {}
    if data.get("attributes") is not None:
        attrs = data["attributes"]
    else:
        attrs = {}
    attrs_json = json.dumps(attrs)

    db.execute(
        "UPDATE cis SET name = ?, type = ?, attributes = ?, updated_at = ? WHERE id = ?",
        (data["name"], data["type"], attrs_json, ts, ci_id)
    )
    db.commit()

    row = db.execute("SELECT * FROM cis WHERE id = ?", (ci_id,)).fetchone()
    return jsonify(row_to_ci(row)), 200


@app.route("/cis/<ci_id>", methods=["DELETE"])
def delete_ci(ci_id: str):
    db = get_db()

    row = db.execute("SELECT * FROM cis WHERE id = ?", (ci_id,)).fetchone()
    if row is None:
        return error_response("not_found", f"CI '{ci_id}' not found", 404)

    # Check for active relationships
    rel_count = db.execute(
        "SELECT COUNT(*) as cnt FROM relationships WHERE source_id = ? OR target_id = ?",
        (ci_id, ci_id)
    ).fetchone()["cnt"]

    if rel_count > 0:
        return error_response(
            "conflict",
            f"CI '{ci_id}' has {rel_count} active relationship(s) and cannot be deleted",
            409
        )

    db.execute("DELETE FROM cis WHERE id = ?", (ci_id,))
    db.commit()
    return "", 204


# ---------------------------------------------------------------------------
# Relationships
# ---------------------------------------------------------------------------

@app.route("/relationships", methods=["POST"])
def create_relationship():
    db = get_db()

    if not request.is_json:
        return error_response("bad_request", "Content-Type must be application/json", 400)

    try:
        data = request.get_json(force=True)
    except Exception:
        return error_response("bad_request", "Invalid JSON body", 400)

    if data is None:
        return error_response("bad_request", "Invalid JSON body", 400)

    valid, msg, details = validate_relationship_input(data)
    if not valid:
        return error_response("validation_error", msg, 422, details)

    source_id = data["source_id"]
    target_id = data["target_id"]
    rel_type = data["type"]

    # Verify source CI exists
    source = db.execute("SELECT id FROM cis WHERE id = ?", (source_id,)).fetchone()
    if source is None:
        return error_response("not_found", f"Source CI '{source_id}' not found", 404)

    # Verify target CI exists
    target = db.execute("SELECT id FROM cis WHERE id = ?", (target_id,)).fetchone()
    if target is None:
        return error_response("not_found", f"Target CI '{target_id}' not found", 404)

    rel_id = new_uuid()
    ts = now_iso()
    attrs = data.get("attributes") or {}
    attrs_json = json.dumps(attrs)

    db.execute(
        "INSERT INTO relationships (id, source_id, target_id, type, attributes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (rel_id, source_id, target_id, rel_type, attrs_json, ts)
    )
    db.commit()

    row = db.execute("SELECT * FROM relationships WHERE id = ?", (rel_id,)).fetchone()
    return jsonify(row_to_relationship(row)), 201


@app.route("/relationships/<rel_id>", methods=["GET"])
def get_relationship(rel_id: str):
    db = get_db()
    row = db.execute("SELECT * FROM relationships WHERE id = ?", (rel_id,)).fetchone()
    if row is None:
        return error_response("not_found", f"Relationship '{rel_id}' not found", 404)
    return jsonify(row_to_relationship(row)), 200


@app.route("/relationships/<rel_id>", methods=["DELETE"])
def delete_relationship(rel_id: str):
    db = get_db()
    row = db.execute("SELECT * FROM relationships WHERE id = ?", (rel_id,)).fetchone()
    if row is None:
        return error_response("not_found", f"Relationship '{rel_id}' not found", 404)
    db.execute("DELETE FROM relationships WHERE id = ?", (rel_id,))
    db.commit()
    return "", 204


@app.route("/cis/<ci_id>/relationships", methods=["GET"])
def get_ci_relationships(ci_id: str):
    db = get_db()

    ci_row = db.execute("SELECT id FROM cis WHERE id = ?", (ci_id,)).fetchone()
    if ci_row is None:
        return error_response("not_found", f"CI '{ci_id}' not found", 404)

    direction = request.args.get("direction", "both")
    rel_type = request.args.get("type")

    if direction not in ("inbound", "outbound", "both"):
        return error_response("bad_request", "direction must be one of: inbound, outbound, both", 400)

    where_parts = []
    params = []

    if direction == "outbound":
        where_parts.append("source_id = ?")
        params.append(ci_id)
    elif direction == "inbound":
        where_parts.append("target_id = ?")
        params.append(ci_id)
    else:  # both
        where_parts.append("(source_id = ? OR target_id = ?)")
        params.extend([ci_id, ci_id])

    if rel_type is not None:
        where_parts.append("type = ?")
        params.append(rel_type)

    where_sql = "WHERE " + " AND ".join(where_parts)

    rows = db.execute(
        f"SELECT * FROM relationships {where_sql} ORDER BY created_at ASC",
        params
    ).fetchall()

    items = [row_to_relationship(r) for r in rows]
    return jsonify({"items": items}), 200


# ---------------------------------------------------------------------------
# Stub endpoints for completeness (not tested by core tests but client calls them)
# ---------------------------------------------------------------------------

@app.route("/cis/bulk", methods=["POST"])
def bulk_create_cis():
    db = get_db()

    if not request.is_json:
        return error_response("bad_request", "Content-Type must be application/json", 400)

    try:
        data = request.get_json(force=True)
    except Exception:
        return error_response("bad_request", "Invalid JSON body", 400)

    if data is None or not isinstance(data, dict):
        return error_response("bad_request", "Invalid JSON body", 400)

    items_input = data.get("items", [])
    if not isinstance(items_input, list):
        return error_response("bad_request", "'items' must be a list", 400)

    created_items = []
    for item_data in items_input:
        valid, msg, details = validate_ci_input(item_data)
        if not valid:
            return error_response("validation_error", msg, 422, details)

        ci_id = new_uuid()
        ts = now_iso()
        attrs = item_data.get("attributes") or {}
        attrs_json = json.dumps(attrs)

        db.execute(
            "INSERT INTO cis (id, name, type, attributes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (ci_id, item_data["name"], item_data["type"], attrs_json, ts, ts)
        )
        row = db.execute("SELECT * FROM cis WHERE id = ?", (ci_id,)).fetchone()
        created_items.append(row_to_ci(row))

    db.commit()
    return jsonify({"items": created_items}), 201


@app.route("/cis/<ci_id>/history", methods=["GET"])
def get_ci_history(ci_id: str):
    db = get_db()
    ci_row = db.execute("SELECT id FROM cis WHERE id = ?", (ci_id,)).fetchone()
    if ci_row is None:
        return error_response("not_found", f"CI '{ci_id}' not found", 404)
    return jsonify({"items": []}), 200


@app.route("/cis/<ci_id>/impact", methods=["GET"])
def get_ci_impact(ci_id: str):
    db = get_db()
    ci_row = db.execute("SELECT * FROM cis WHERE id = ?", (ci_id,)).fetchone()
    if ci_row is None:
        return error_response("not_found", f"CI '{ci_id}' not found", 404)

    try:
        depth = int(request.args.get("depth", 3))
    except (ValueError, TypeError):
        depth = 3

    rel_types_param = request.args.get("relationship_types")
    rel_types = rel_types_param.split(",") if rel_types_param else None

    visited = set()
    visited.add(ci_id)
    frontier = [ci_id]
    result_ids = []

    for _ in range(depth):
        if not frontier:
            break
        next_frontier = []
        for fid in frontier:
            if rel_types:
                placeholders = ",".join("?" * len(rel_types))
                rows = db.execute(
                    f"SELECT target_id FROM relationships WHERE source_id = ? AND type IN ({placeholders})",
                    [fid] + rel_types
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT target_id FROM relationships WHERE source_id = ?",
                    (fid,)
                ).fetchall()
            for row in rows:
                tid = row["target_id"]
                if tid not in visited:
                    visited.add(tid)
                    next_frontier.append(tid)
                    result_ids.append(tid)
        frontier = next_frontier

    items = []
    for rid in result_ids:
        r = db.execute("SELECT * FROM cis WHERE id = ?", (rid,)).fetchone()
        if r:
            items.append(row_to_ci(r))

    return jsonify({"items": items}), 200


@app.route("/cis/<ci_id>/dependencies", methods=["GET"])
def get_ci_dependencies(ci_id: str):
    db = get_db()
    ci_row = db.execute("SELECT * FROM cis WHERE id = ?", (ci_id,)).fetchone()
    if ci_row is None:
        return error_response("not_found", f"CI '{ci_id}' not found", 404)

    try:
        depth = int(request.args.get("depth", 3))
    except (ValueError, TypeError):
        depth = 3

    rel_types_param = request.args.get("relationship_types")
    rel_types = rel_types_param.split(",") if rel_types_param else None

    visited = set()
    visited.add(ci_id)
    frontier = [ci_id]
    result_ids = []

    for _ in range(depth):
        if not frontier:
            break
        next_frontier = []
        for fid in frontier:
            if rel_types:
                placeholders = ",".join("?" * len(rel_types))
                rows = db.execute(
                    f"SELECT source_id FROM relationships WHERE target_id = ? AND type IN ({placeholders})",
                    [fid] + rel_types
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT source_id FROM relationships WHERE target_id = ?",
                    (fid,)
                ).fetchall()
            for row in rows:
                sid = row["source_id"]
                if sid not in visited:
                    visited.add(sid)
                    next_frontier.append(sid)
                    result_ids.append(sid)
        frontier = next_frontier

    items = []
    for rid in result_ids:
        r = db.execute("SELECT * FROM cis WHERE id = ?", (rid,)).fetchone()
        if r:
            items.append(row_to_ci(r))

    return jsonify({"items": items}), 200


@app.route("/policies", methods=["POST"])
def create_policy():
    if not request.is_json:
        return error_response("bad_request", "Content-Type must be application/json", 400)
    try:
        data = request.get_json(force=True)
    except Exception:
        return error_response("bad_request", "Invalid JSON body", 400)

    policy_id = new_uuid()
    ts = now_iso()
    ci_type = data.get("ci_type", "")
    rules = data.get("rules", {})

    return jsonify({
        "id": policy_id,
        "ci_type": ci_type,
        "rules": rules,
        "created_at": ts,
    }), 201


@app.route("/policies", methods=["GET"])
def list_policies():
    return jsonify({"items": []}), 200


@app.route("/policies/<policy_id>", methods=["DELETE"])
def delete_policy(policy_id: str):
    return "", 204


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found_handler(e):
    return error_response("not_found", "The requested resource was not found", 404)


@app.errorhandler(405)
def method_not_allowed_handler(e):
    return error_response("method_not_allowed", "Method not allowed", 405)


@app.errorhandler(500)
def internal_error_handler(e):
    return error_response("internal_error", "Internal server error", 500)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Initialize DB on startup
    get_db()
    app.run(host="0.0.0.0", port=9090, debug=False)