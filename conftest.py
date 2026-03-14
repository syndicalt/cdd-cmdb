"""Root conftest — shared fixtures available to all test suites.

Configuration via environment variables:
  CMDB_BASE_URL       Target CMDB instance  (default: http://localhost:8080)
  HYPOTHESIS_PROFILE  'ci' (fast) or 'release' (thorough)  (default: ci)
"""
from __future__ import annotations

import os
import pytest
from hypothesis import settings, HealthCheck

from harness.client import CMDBClient, CI, Relationship

# ---------------------------------------------------------------------------
# Hypothesis profiles
# ---------------------------------------------------------------------------

settings.register_profile(
    "ci",
    max_examples=25,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "release",
    max_examples=500,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))

# ---------------------------------------------------------------------------
# Client fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def client() -> CMDBClient:
    c = CMDBClient()
    yield c
    c.close()


@pytest.fixture
def make_ci(client: CMDBClient):
    """Factory fixture: creates a CI and auto-deletes it after the test.

    Usage:
        def test_something(make_ci):
            ci = make_ci("my-server", type="server")
    """
    created: list[CI] = []

    def _make(name: str, type: str = "generic", attributes: dict | None = None) -> CI:
        ci = client.create_ci(name=name, type=type, attributes=attributes)
        created.append(ci)
        return ci

    yield _make

    for ci in reversed(created):
        try:
            client.delete_ci(ci.id)
        except Exception:
            pass  # Already deleted by the test (e.g. delete tests)


@pytest.fixture
def make_relationship(client: CMDBClient):
    """Factory fixture: creates a relationship and auto-deletes it after the test."""
    created: list[Relationship] = []

    def _make(source_id: str, target_id: str, type: str = "related_to") -> Relationship:
        rel = client.create_relationship(source_id=source_id, target_id=target_id, type=type)
        created.append(rel)
        return rel

    yield _make

    for rel in reversed(created):
        try:
            client.delete_relationship(rel.id)
        except Exception:
            pass
