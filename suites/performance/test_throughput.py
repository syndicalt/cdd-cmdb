"""Throughput tests.

Verify the CMDB can handle bulk workloads within time budgets.

SLAs (configurable via env vars):
- Bulk create 100 CIs:  CMDB_SLA_BULK_100_MS (default 5000ms)
- Sequential CRUD x50:  CMDB_SLA_SEQ_50_MS   (default 10000ms)
"""
from __future__ import annotations

import os
import time
import pytest

from harness.client import CMDBClient

SLA_BULK_100_MS = int(os.environ.get("CMDB_SLA_BULK_100_MS", "5000"))
SLA_SEQ_50_MS = int(os.environ.get("CMDB_SLA_SEQ_50_MS", "10000"))


def elapsed_ms(start: float) -> float:
    return (time.monotonic() - start) * 1000


class TestBulkThroughput:
    def test_bulk_create_100_within_sla(self, client: CMDBClient):
        items = [
            {"name": f"throughput-{i}", "type": "server", "attributes": {"index": i}}
            for i in range(100)
        ]
        start = time.monotonic()
        created = client.bulk_create_cis(items)
        ms = elapsed_ms(start)
        try:
            assert len(created) == 100
            assert ms < SLA_BULK_100_MS, (
                f"Bulk create 100 took {ms:.0f}ms (SLA: {SLA_BULK_100_MS}ms)"
            )
        finally:
            for ci in created:
                try:
                    client.delete_ci(ci.id)
                except Exception:
                    pass


class TestSequentialThroughput:
    def test_sequential_crud_50_within_sla(self, client: CMDBClient):
        """50 full CRUD cycles (create-read-update-delete) in sequence."""
        start = time.monotonic()
        for i in range(50):
            ci = client.create_ci(name=f"seq-{i}", type="server")
            client.get_ci(ci.id)
            client.update_ci(ci.id, name=f"seq-{i}-updated", type="server")
            client.delete_ci(ci.id)
        ms = elapsed_ms(start)
        assert ms < SLA_SEQ_50_MS, (
            f"50 sequential CRUD cycles took {ms:.0f}ms (SLA: {SLA_SEQ_50_MS}ms)"
        )
