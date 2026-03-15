"""Authentication and authorization tests.

These tests verify that the CMDB enforces access control when configured.
Skipped when CMDB_AUTH_ENABLED is not set — not all deployments require auth.

Invariants:
- Unauthenticated requests to protected endpoints return 401
- Invalid/expired tokens return 401
- Read-only tokens cannot perform writes (403)
- Auth headers are never echoed back in response bodies
"""
from __future__ import annotations

import os

import pytest

from harness.client import CMDBClient

# Skip entire module if auth is not enabled for this instance
pytestmark = pytest.mark.skipif(
    os.environ.get("CMDB_AUTH_ENABLED", "").lower() not in ("1", "true", "yes"),
    reason="CMDB_AUTH_ENABLED not set — auth tests skipped",
)

PROTECTED_ENDPOINTS = [
    ("GET", "/cis"),
    ("POST", "/cis"),
    ("GET", "/cis/00000000-0000-0000-0000-000000000000"),
    ("PUT", "/cis/00000000-0000-0000-0000-000000000000"),
    ("DELETE", "/cis/00000000-0000-0000-0000-000000000000"),
    ("GET", "/relationships"),
    ("POST", "/relationships"),
]


class TestUnauthenticatedAccess:
    @pytest.mark.parametrize("method,path", PROTECTED_ENDPOINTS)
    def test_no_token_returns_401(self, client: CMDBClient, method: str, path: str):
        """Requests without credentials must be rejected."""
        resp = client.raw_request(
            method, path,
            headers={"Authorization": ""},
            json={"name": "test", "type": "server"} if method in ("POST", "PUT") else None,
        )
        assert resp.status_code == 401, (
            f"{method} {path} without auth returned {resp.status_code}, expected 401"
        )


class TestInvalidCredentials:
    @pytest.mark.parametrize("bad_token", [
        "Bearer invalid-token-12345",
        "Bearer ",
        "Basic dXNlcjpwYXNz",  # wrong scheme if JWT expected
        "garbage",
    ])
    def test_bad_token_returns_401(self, client: CMDBClient, bad_token: str):
        resp = client.raw_request(
            "GET", "/cis",
            headers={"Authorization": bad_token},
        )
        assert resp.status_code == 401


class TestAuthHeaderNotLeaked:
    def test_error_response_does_not_echo_token(self, client: CMDBClient):
        """Auth credentials must never appear in response bodies."""
        secret = "Bearer super-secret-token-xyz"
        resp = client.raw_request(
            "GET", "/cis/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": secret},
        )
        body = resp.text
        assert "super-secret-token-xyz" not in body, (
            "Auth token was echoed in the response body"
        )


class TestReadOnlyAccess:
    """When CMDB_READONLY_TOKEN is set, verify it can read but not write."""

    pytestmark = pytest.mark.skipif(
        not os.environ.get("CMDB_READONLY_TOKEN"),
        reason="CMDB_READONLY_TOKEN not set",
    )

    @pytest.fixture
    def readonly_headers(self):
        return {"Authorization": f"Bearer {os.environ['CMDB_READONLY_TOKEN']}"}

    def test_read_allowed(self, client: CMDBClient, readonly_headers):
        resp = client.raw_request("GET", "/cis", headers=readonly_headers)
        assert resp.status_code == 200

    def test_write_forbidden(self, client: CMDBClient, readonly_headers):
        resp = client.raw_request(
            "POST", "/cis",
            headers=readonly_headers,
            json={"name": "should-fail", "type": "server"},
        )
        assert resp.status_code == 403, (
            f"Read-only token was allowed to create a CI (got {resp.status_code})"
        )
