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
    tags: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "CI":
        return cls(
            id=d["id"],
            name=d["name"],
            type=d["type"],
            attributes=d.get("attributes") or {},
            tags=d.get("tags") or [],
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


@dataclass
class TagSummary:
    tag: str
    count: int

    @classmethod
    def from_dict(cls, d: dict) -> "TagSummary":
        return cls(tag=d["tag"], count=d["count"])


@dataclass
class TTLInfo:
    ci_id: str
    expires_at: str
    status: str  # "active", "expired"
    last_seen: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "TTLInfo":
        return cls(
            ci_id=d["ci_id"],
            expires_at=d.get("expires_at", ""),
            status=d.get("status", "active"),
            last_seen=d.get("last_seen", ""),
        )


@dataclass
class Webhook:
    id: str
    url: str
    events: list[str] = field(default_factory=list)
    active: bool = True
    created_at: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Webhook":
        return cls(
            id=d["id"],
            url=d["url"],
            events=d.get("events") or [],
            active=d.get("active", True),
            created_at=d.get("created_at", ""),
        )


@dataclass
class WebhookDelivery:
    id: str
    webhook_id: str
    event: str
    success: bool = False
    status_code: int | None = None
    timestamp: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "WebhookDelivery":
        return cls(
            id=d["id"],
            webhook_id=d["webhook_id"],
            event=d.get("event", ""),
            success=d.get("success", False),
            status_code=d.get("status_code"),
            timestamp=d.get("timestamp", ""),
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

    # --- Search ---

    def search_cis(
        self,
        q: str | None = None,
        name: str | None = None,
        type: str | None = None,
        attribute_filters: dict[str, str] | None = None,
        sort: str | None = None,
        tag: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CI]:
        """Search CIs with full-text query, filters, wildcards, and sorting."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if q is not None:
            params["q"] = q
        if name is not None:
            params["name"] = name
        if type is not None:
            params["type"] = type
        if sort is not None:
            params["sort"] = sort
        if tag is not None:
            params["tag"] = tag
        if status is not None:
            params["status"] = status
        if attribute_filters:
            for key, value in attribute_filters.items():
                params[f"attributes.{key}"] = value
        resp = self._http.get("/cis/search", params=params)
        _raise(resp)
        data = resp.json()
        return [CI.from_dict(item) for item in data["items"]]

    # --- Diff / Change Tracking ---

    def get_ci_diff(self, ci_id: str, entry_id: str) -> dict:
        """Get attribute-level diff for a specific audit entry."""
        resp = self._http.get(
            f"/cis/{ci_id}/history/{entry_id}/diff",
        )
        _raise(resp)
        return resp.json()

    def get_ci_snapshot(self, ci_id: str, entry_id: str) -> dict:
        """Get the full CI snapshot at a specific audit entry."""
        resp = self._http.get(
            f"/cis/{ci_id}/history/{entry_id}/snapshot",
        )
        _raise(resp)
        return resp.json()

    def get_ci_diff_range(
        self,
        ci_id: str,
        from_ts: str,
        to_ts: str,
    ) -> list[dict]:
        """Get all changes to a CI between two timestamps."""
        resp = self._http.get(
            f"/cis/{ci_id}/diff",
            params={"from": from_ts, "to": to_ts},
        )
        _raise(resp)
        return resp.json().get("changes", [])

    # --- Reconciliation ---

    def reconcile(
        self,
        source: str,
        items: list[dict],
        apply: bool = False,
    ) -> dict:
        """Reconcile a list of CIs from an external source.

        Returns dict with keys: new, updated, unchanged, stale.
        Each is a list of dicts with at minimum a 'name' key.
        """
        resp = self._http.post("/cis/reconcile", json={
            "source": source,
            "items": items,
            "apply": apply,
        })
        _raise(resp)
        return resp.json()

    # --- Tags ---

    def set_ci_tags(self, ci_id: str, tags: list[str]) -> list[str]:
        """PUT /cis/{id}/tags — full replacement."""
        resp = self._http.put(f"/cis/{ci_id}/tags", json={"tags": tags})
        _raise(resp)
        return resp.json().get("tags", [])

    def get_ci_tags(self, ci_id: str) -> list[str]:
        """GET /cis/{id}/tags"""
        resp = self._http.get(f"/cis/{ci_id}/tags")
        _raise(resp)
        return resp.json().get("tags", [])

    def remove_ci_tag(self, ci_id: str, tag: str) -> None:
        """DELETE /cis/{id}/tags/{tag}"""
        resp = self._http.delete(f"/cis/{ci_id}/tags/{tag}")
        _raise(resp)

    def list_tags(self) -> list[TagSummary]:
        """GET /tags — all known tags with usage counts."""
        resp = self._http.get("/tags")
        _raise(resp)
        return [TagSummary.from_dict(t) for t in resp.json()["items"]]

    # --- TTL / Expiry ---

    def set_ci_ttl(self, ci_id: str, expires_at: str) -> TTLInfo:
        """PUT /cis/{id}/ttl"""
        resp = self._http.put(f"/cis/{ci_id}/ttl", json={"expires_at": expires_at})
        _raise(resp)
        return TTLInfo.from_dict(resp.json())

    def get_ci_ttl(self, ci_id: str) -> TTLInfo:
        """GET /cis/{id}/ttl"""
        resp = self._http.get(f"/cis/{ci_id}/ttl")
        _raise(resp)
        return TTLInfo.from_dict(resp.json())

    def remove_ci_ttl(self, ci_id: str) -> None:
        """DELETE /cis/{id}/ttl"""
        resp = self._http.delete(f"/cis/{ci_id}/ttl")
        _raise(resp)

    def trigger_expiry(self) -> dict:
        """POST /cis/expire — returns {expired: int}"""
        resp = self._http.post("/cis/expire", json={})
        _raise(resp)
        return resp.json()

    # --- Webhooks ---

    def create_webhook(self, url: str, events: list[str]) -> Webhook:
        """POST /webhooks"""
        resp = self._http.post("/webhooks", json={"url": url, "events": events})
        _raise(resp)
        return Webhook.from_dict(resp.json())

    def list_webhooks(self) -> list[Webhook]:
        """GET /webhooks"""
        resp = self._http.get("/webhooks")
        _raise(resp)
        return [Webhook.from_dict(w) for w in resp.json()["items"]]

    def get_webhook(self, webhook_id: str) -> Webhook:
        """GET /webhooks/{id}"""
        resp = self._http.get(f"/webhooks/{webhook_id}")
        _raise(resp)
        return Webhook.from_dict(resp.json())

    def delete_webhook(self, webhook_id: str) -> None:
        """DELETE /webhooks/{id}"""
        resp = self._http.delete(f"/webhooks/{webhook_id}")
        _raise(resp)

    def get_webhook_deliveries(self, webhook_id: str) -> list[WebhookDelivery]:
        """GET /webhooks/{id}/deliveries"""
        resp = self._http.get(f"/webhooks/{webhook_id}/deliveries")
        _raise(resp)
        return [WebhookDelivery.from_dict(d) for d in resp.json()["items"]]

    def test_webhook(self, webhook_id: str) -> WebhookDelivery:
        """POST /webhooks/{id}/test — triggers a ping delivery."""
        resp = self._http.post(f"/webhooks/{webhook_id}/test", json={})
        _raise(resp)
        return WebhookDelivery.from_dict(resp.json())

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
