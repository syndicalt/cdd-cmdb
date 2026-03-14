"""API latency SLA tests.

These define upper-bound response times for single operations.
Any compliant CMDB instance must meet these under normal load.

SLAs (configurable via env vars):
- Single CRUD operation:   CMDB_SLA_CRUD_MS      (default 500ms)
- List with pagination:    CMDB_SLA_LIST_MS      (default 1000ms)
- Relationship query:      CMDB_SLA_REL_QUERY_MS (default 1000ms)
- Health check:            CMDB_SLA_HEALTH_MS    (default 200ms)
"""
from __future__ import annotations

import os
import time
import pytest

from harness.client import CMDBClient

SLA_CRUD_MS = int(os.environ.get("CMDB_SLA_CRUD_MS", "500"))
SLA_LIST_MS = int(os.environ.get("CMDB_SLA_LIST_MS", "1000"))
SLA_REL_QUERY_MS = int(os.environ.get("CMDB_SLA_REL_QUERY_MS", "1000"))
SLA_HEALTH_MS = int(os.environ.get("CMDB_SLA_HEALTH_MS", "200"))


def elapsed_ms(start: float) -> float:
    return (time.monotonic() - start) * 1000


class TestHealthLatency:
    def test_health_within_sla(self, client: CMDBClient):
        start = time.monotonic()
        client.health()
        ms = elapsed_ms(start)
        assert ms < SLA_HEALTH_MS, f"Health check took {ms:.0f}ms (SLA: {SLA_HEALTH_MS}ms)"


class TestCRUDLatency:
    def test_create_within_sla(self, client: CMDBClient):
        start = time.monotonic()
        ci = client.create_ci(name="latency-create", type="server")
        ms = elapsed_ms(start)
        client.delete_ci(ci.id)
        assert ms < SLA_CRUD_MS, f"Create took {ms:.0f}ms (SLA: {SLA_CRUD_MS}ms)"

    def test_read_within_sla(self, make_ci, client: CMDBClient):
        ci = make_ci("latency-read", type="server")
        start = time.monotonic()
        client.get_ci(ci.id)
        ms = elapsed_ms(start)
        assert ms < SLA_CRUD_MS, f"Read took {ms:.0f}ms (SLA: {SLA_CRUD_MS}ms)"

    def test_update_within_sla(self, make_ci, client: CMDBClient):
        ci = make_ci("latency-update", type="server")
        start = time.monotonic()
        client.update_ci(ci.id, name="updated-name", type="server")
        ms = elapsed_ms(start)
        assert ms < SLA_CRUD_MS, f"Update took {ms:.0f}ms (SLA: {SLA_CRUD_MS}ms)"

    def test_delete_within_sla(self, client: CMDBClient):
        ci = client.create_ci(name="latency-delete", type="server")
        start = time.monotonic()
        client.delete_ci(ci.id)
        ms = elapsed_ms(start)
        assert ms < SLA_CRUD_MS, f"Delete took {ms:.0f}ms (SLA: {SLA_CRUD_MS}ms)"


class TestListLatency:
    def test_list_within_sla(self, client: CMDBClient):
        start = time.monotonic()
        client.list_cis(limit=100)
        ms = elapsed_ms(start)
        assert ms < SLA_LIST_MS, f"List took {ms:.0f}ms (SLA: {SLA_LIST_MS}ms)"

    def test_list_with_type_filter_within_sla(self, make_ci, client: CMDBClient):
        for i in range(10):
            make_ci(f"latency-filter-{i}", type="perf_test")
        start = time.monotonic()
        client.list_cis(type="perf_test")
        ms = elapsed_ms(start)
        assert ms < SLA_LIST_MS, f"Filtered list took {ms:.0f}ms (SLA: {SLA_LIST_MS}ms)"


class TestRelationshipQueryLatency:
    def test_ci_relationships_within_sla(self, make_ci, make_relationship, client: CMDBClient):
        a = make_ci("latency-rel-src", type="server")
        b = make_ci("latency-rel-tgt", type="app")
        make_relationship(a.id, b.id, type="hosts")
        start = time.monotonic()
        client.get_ci_relationships(a.id)
        ms = elapsed_ms(start)
        assert ms < SLA_REL_QUERY_MS, (
            f"Relationship query took {ms:.0f}ms (SLA: {SLA_REL_QUERY_MS}ms)"
        )
