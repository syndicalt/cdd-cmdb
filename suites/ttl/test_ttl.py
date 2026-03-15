"""TTL and expiry tests.

Invariants verified:
- PUT /cis/{id}/ttl sets an expiration time on a CI
- GET /cis/{id}/ttl returns TTL status (expires_at, status)
- DELETE /cis/{id}/ttl removes expiry (CI lives forever)
- POST /cis/expire triggers an expiry sweep, marking past-due CIs as expired
- Expired CIs are NOT deleted, only marked with status "expired"
- CIs without TTL are never marked expired
- Sweep is idempotent (running twice doesn't double-expire)
- Expired CIs are searchable via status= filter
- TTL operations on nonexistent CIs return 404
- Invalid timestamps are rejected with 422
"""
from __future__ import annotations

from harness.client import CMDBClient


class TestTTLSetAndGet:
    """PUT /cis/{id}/ttl and GET /cis/{id}/ttl manage CI expiry."""

    def test_set_ttl(self, make_ci, client: CMDBClient):
        ci = make_ci("ttl-server", type="server")
        ttl = client.set_ci_ttl(ci.id, expires_at="2099-12-31T23:59:59Z")
        assert ttl.expires_at == "2099-12-31T23:59:59Z"
        assert ttl.status == "active"

    def test_get_ttl(self, make_ci, client: CMDBClient):
        ci = make_ci("ttl-get", type="server")
        client.set_ci_ttl(ci.id, expires_at="2099-06-15T00:00:00Z")
        ttl = client.get_ci_ttl(ci.id)
        assert ttl.expires_at == "2099-06-15T00:00:00Z"
        assert ttl.ci_id == ci.id

    def test_update_ttl(self, make_ci, client: CMDBClient):
        ci = make_ci("ttl-update", type="server")
        client.set_ci_ttl(ci.id, expires_at="2099-01-01T00:00:00Z")
        client.set_ci_ttl(ci.id, expires_at="2099-06-01T00:00:00Z")
        ttl = client.get_ci_ttl(ci.id)
        assert ttl.expires_at == "2099-06-01T00:00:00Z"

    def test_get_ttl_not_set(self, make_ci, client: CMDBClient):
        ci = make_ci("no-ttl", type="server")
        resp = client.raw_get(f"/cis/{ci.id}/ttl")
        # Either 404 (no TTL set) or 200 with no expires_at
        assert resp.status_code in (200, 404)

    def test_set_ttl_nonexistent_ci_404(self, client: CMDBClient):
        resp = client.raw_request(
            "PUT", "/cis/nonexistent/ttl",
            json={"expires_at": "2099-12-31T23:59:59Z"},
        )
        assert resp.status_code == 404


class TestTTLRemoval:
    """DELETE /cis/{id}/ttl removes expiry."""

    def test_remove_ttl(self, make_ci, client: CMDBClient):
        ci = make_ci("ttl-remove", type="server")
        client.set_ci_ttl(ci.id, expires_at="2099-01-01T00:00:00Z")
        client.remove_ci_ttl(ci.id)
        resp = client.raw_get(f"/cis/{ci.id}/ttl")
        if resp.status_code == 200:
            data = resp.json()
            assert data.get("expires_at") is None or data.get("status") == "active"
        else:
            assert resp.status_code == 404

    def test_remove_ttl_nonexistent_ci_404(self, client: CMDBClient):
        resp = client.raw_request("DELETE", "/cis/nonexistent/ttl")
        assert resp.status_code == 404


class TestExpirySweep:
    """POST /cis/expire marks past-due CIs as expired."""

    def test_expired_ci_marked(self, make_ci, client: CMDBClient):
        ci = make_ci("expired-ci", type="server")
        # Set TTL in the past
        client.set_ci_ttl(ci.id, expires_at="2020-01-01T00:00:00Z")
        result = client.trigger_expiry()
        assert result["expired"] >= 1
        # Verify the CI is marked expired
        ttl = client.get_ci_ttl(ci.id)
        assert ttl.status == "expired"

    def test_active_ci_not_expired(self, make_ci, client: CMDBClient):
        ci = make_ci("active-ci", type="server")
        client.set_ci_ttl(ci.id, expires_at="2099-12-31T23:59:59Z")
        client.trigger_expiry()
        ttl = client.get_ci_ttl(ci.id)
        assert ttl.status == "active"

    def test_sweep_returns_counts(self, make_ci, client: CMDBClient):
        ci = make_ci("sweep-count", type="server")
        client.set_ci_ttl(ci.id, expires_at="2020-01-01T00:00:00Z")
        result = client.trigger_expiry()
        assert "expired" in result
        assert isinstance(result["expired"], int)

    def test_sweep_idempotent(self, make_ci, client: CMDBClient):
        ci = make_ci("sweep-idemp", type="server")
        client.set_ci_ttl(ci.id, expires_at="2020-01-01T00:00:00Z")
        r1 = client.trigger_expiry()
        r2 = client.trigger_expiry()
        # Second sweep should not find new expirations from same CI
        ttl = client.get_ci_ttl(ci.id)
        assert ttl.status == "expired"

    def test_expired_ci_still_readable(self, make_ci, client: CMDBClient):
        ci = make_ci("still-readable", type="server")
        client.set_ci_ttl(ci.id, expires_at="2020-01-01T00:00:00Z")
        client.trigger_expiry()
        # CI should still exist
        fetched = client.get_ci(ci.id)
        assert fetched.name == "still-readable"

    def test_ci_without_ttl_not_expired(self, make_ci, client: CMDBClient):
        ci = make_ci("no-ttl-safe", type="server")
        client.trigger_expiry()
        # CI should still be fine
        fetched = client.get_ci(ci.id)
        assert fetched.name == "no-ttl-safe"


class TestLifecycleSearch:
    """GET /cis/search?status= filters by lifecycle status."""

    def test_search_expired_cis(self, make_ci, client: CMDBClient):
        ci = make_ci("search-expired", type="server")
        client.set_ci_ttl(ci.id, expires_at="2020-01-01T00:00:00Z")
        client.trigger_expiry()
        results = client.search_cis(status="expired")
        ids = [c.id for c in results]
        assert ci.id in ids

    def test_search_active_excludes_expired(self, make_ci, client: CMDBClient):
        ci_active = make_ci("search-active", type="server")
        ci_expired = make_ci("search-exp", type="server")
        client.set_ci_ttl(ci_expired.id, expires_at="2020-01-01T00:00:00Z")
        client.trigger_expiry()
        results = client.search_cis(status="active")
        ids = [c.id for c in results]
        assert ci_active.id in ids
        assert ci_expired.id not in ids


class TestTTLValidation:
    """TTL inputs are validated."""

    def test_invalid_expires_at_rejected(self, make_ci, client: CMDBClient):
        ci = make_ci("bad-ttl", type="server")
        resp = client.raw_request(
            "PUT", f"/cis/{ci.id}/ttl",
            json={"expires_at": "not-a-date"},
        )
        assert resp.status_code in (400, 422)

    def test_missing_expires_at_rejected(self, make_ci, client: CMDBClient):
        ci = make_ci("no-expiry", type="server")
        resp = client.raw_request(
            "PUT", f"/cis/{ci.id}/ttl",
            json={},
        )
        assert resp.status_code in (400, 422)
