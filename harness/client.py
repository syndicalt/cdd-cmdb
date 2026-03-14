"""Thin HTTP client for the CMDB API under test.

All test suites MUST use this client — never call httpx directly.
The only configuration needed is CMDB_BASE_URL.

No test should import implementation code. State is set up exclusively
through this client (i.e. through the API under test).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import httpx

CMDB_BASE_URL = os.environ.get("CMDB_BASE_URL", "http://localhost:8080")


# ---------------------------------------------------------------------------
# Typed exceptions — tests assert on these, not on status codes
# ---------------------------------------------------------------------------

class CMDBError(Exception):
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self.body = body
        super().__init__(f"HTTP {status_code}: {body}")


class NotFoundError(CMDBError): ...
class ConflictError(CMDBError): ...
class ValidationError(CMDBError): ...
class BadRequestError(CMDBError): ...
class AuthError(CMDBError): ...
class ForbiddenError(CMDBError): ...


def _raise(resp: httpx.Response) -> None:
    if resp.status_code < 400:
        return
    body: dict = {}
    try:
        body = resp.json()
    except Exception:
        pass
    match resp.status_code:
        case 400:
            raise BadRequestError(resp.status_code, body)
        case 401:
            raise AuthError(resp.status_code, body)
        case 403:
            raise ForbiddenError(resp.status_code, body)
        case 404:
            raise NotFoundError(resp.status_code, body)
        case 409:
            raise ConflictError(resp.status_code, body)
        case 422:
            raise ValidationError(resp.status_code, body)
        case _:
            raise CMDBError(resp.status_code, body)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

@dataclass
class CI:
    id: str
    name: str
    type: str
    attributes: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "CI":
        return cls(
            id=d["id"],
            name=d["name"],
            type=d["type"],
            attributes=d.get("attributes") or {},
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
        )


@dataclass
class AuditEntry:
    id: str
    ci_id: str
    action: str  # "created", "updated", "deleted"
    changes: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    actor: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "AuditEntry":
        return cls(
            id=d["id"],
            ci_id=d["ci_id"],
            action=d["action"],
            changes=d.get("changes") or {},
            timestamp=d.get("timestamp", ""),
            actor=d.get("actor", ""),
        )


@dataclass
class Policy:
    id: str
    ci_type: str
    rules: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Policy":
        return cls(
            id=d["id"],
            ci_type=d["ci_type"],
            rules=d.get("rules") or {},
            created_at=d.get("created_at", ""),
        )


@dataclass
class Relationship:
    id: str
    source_id: str
    target_id: str
    type: str
    attributes: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Relationship":
        return cls(
            id=d["id"],
            source_id=d["source_id"],
            target_id=d["target_id"],
            type=d["type"],
            attributes=d.get("attributes") or {},
            created_at=d.get("created_at", ""),
        )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class CMDBClient:
    def __init__(self, base_url: str = CMDB_BASE_URL):
        self._http = httpx.Client(base_url=base_url, timeout=10.0)

    def close(self) -> None:
        self._http.close()

    # --- Health ---

    def health(self) -> dict:
        resp = self._http.get("/health")
        _raise(resp)
        return resp.json()

    # --- CIs ---

    def create_ci(self, name: str, type: str, attributes: dict | None = None) -> CI:
        payload: dict = {"name": name, "type": type}
        if attributes:
            payload["attributes"] = attributes
        resp = self._http.post("/cis", json=payload)
        _raise(resp)
        return CI.from_dict(resp.json())

    def get_ci(self, ci_id: str) -> CI:
        resp = self._http.get(f"/cis/{ci_id}")
        _raise(resp)
        return CI.from_dict(resp.json())

    def update_ci(self, ci_id: str, name: str, type: str, attributes: dict | None = None) -> CI:
        payload: dict = {"name": name, "type": type}
        if attributes is not None:
            payload["attributes"] = attributes
        resp = self._http.put(f"/cis/{ci_id}", json=payload)
        _raise(resp)
        return CI.from_dict(resp.json())

    def delete_ci(self, ci_id: str) -> None:
        resp = self._http.delete(f"/cis/{ci_id}")
        _raise(resp)

    def list_cis(
        self,
        type: str | None = None,
        name: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[CI], int]:
        params: dict = {"limit": limit, "offset": offset}
        if type:
            params["type"] = type
        if name:
            params["name"] = name
        resp = self._http.get("/cis", params=params)
        _raise(resp)
        data = resp.json()
        return [CI.from_dict(item) for item in data["items"]], data["total"]

    # --- Relationships ---

    def create_relationship(
        self,
        source_id: str,
        target_id: str,
        type: str,
        attributes: dict | None = None,
    ) -> Relationship:
        payload: dict = {"source_id": source_id, "target_id": target_id, "type": type}
        if attributes:
            payload["attributes"] = attributes
        resp = self._http.post("/relationships", json=payload)
        _raise(resp)
        return Relationship.from_dict(resp.json())

    def get_relationship(self, rel_id: str) -> Relationship:
        resp = self._http.get(f"/relationships/{rel_id}")
        _raise(resp)
        return Relationship.from_dict(resp.json())

    def delete_relationship(self, rel_id: str) -> None:
        resp = self._http.delete(f"/relationships/{rel_id}")
        _raise(resp)

    def get_ci_relationships(
        self,
        ci_id: str,
        direction: str = "both",
        type: str | None = None,
    ) -> list[Relationship]:
        params: dict = {"direction": direction}
        if type:
            params["type"] = type
        resp = self._http.get(f"/cis/{ci_id}/relationships", params=params)
        _raise(resp)
        return [Relationship.from_dict(r) for r in resp.json()["items"]]

    # --- Bulk operations ---

    def bulk_create_cis(self, items: list[dict]) -> list[CI]:
        resp = self._http.post("/cis/bulk", json={"items": items})
        _raise(resp)
        return [CI.from_dict(ci) for ci in resp.json()["items"]]

    # --- Audit ---

    def get_ci_history(self, ci_id: str) -> list[AuditEntry]:
        resp = self._http.get(f"/cis/{ci_id}/history")
        _raise(resp)
        return [AuditEntry.from_dict(e) for e in resp.json()["items"]]

    # --- Graph traversal ---

    def get_ci_impact(
        self, ci_id: str, depth: int = 3, relationship_types: list[str] | None = None,
    ) -> list[CI]:
        params: dict = {"depth": depth}
        if relationship_types:
            params["relationship_types"] = ",".join(relationship_types)
        resp = self._http.get(f"/cis/{ci_id}/impact", params=params)
        _raise(resp)
        return [CI.from_dict(ci) for ci in resp.json()["items"]]

    def get_ci_dependencies(
        self, ci_id: str, depth: int = 3, relationship_types: list[str] | None = None,
    ) -> list[CI]:
        params: dict = {"depth": depth}
        if relationship_types:
            params["relationship_types"] = ",".join(relationship_types)
        resp = self._http.get(f"/cis/{ci_id}/dependencies", params=params)
        _raise(resp)
        return [CI.from_dict(ci) for ci in resp.json()["items"]]

    # --- Governance / Policies ---

    def create_policy(self, ci_type: str, rules: dict) -> Policy:
        resp = self._http.post("/policies", json={"ci_type": ci_type, "rules": rules})
        _raise(resp)
        return Policy.from_dict(resp.json())

    def list_policies(self) -> list[Policy]:
        resp = self._http.get("/policies")
        _raise(resp)
        return [Policy.from_dict(p) for p in resp.json()["items"]]

    def delete_policy(self, policy_id: str) -> None:
        resp = self._http.delete(f"/policies/{policy_id}")
        _raise(resp)

    # --- Raw access (for validation / negative tests only) ---

    def raw_post(self, path: str, json: dict) -> httpx.Response:
        """Send a raw POST without error-raising. Use only in schema validation tests."""
        return self._http.post(path, json=json)

    def raw_get(self, path: str, **kwargs) -> httpx.Response:
        """Send a raw GET without error-raising."""
        return self._http.get(path, **kwargs)

    def raw_request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """Send a raw request without error-raising."""
        return self._http.request(method, path, **kwargs)
