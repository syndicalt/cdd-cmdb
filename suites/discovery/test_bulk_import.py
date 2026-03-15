"""Bulk import and source-tracking tests.

Discovery in a CMDB context means accepting CIs in bulk from external
sources (cloud APIs, network scanners, agent collectors) and reconciling
them with existing records.

Invariants:
- POST /cis/bulk accepts a list of CI inputs and returns created CIs
- Each returned CI has a unique server-assigned ID
- Bulk-created CIs are individually retrievable via GET /cis/{id}
- Source metadata in attributes survives the round-trip
- Partial failures (some valid, some invalid) are handled gracefully
- Bulk import of zero items returns an empty list, not an error
"""
from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from harness.client import CMDBClient, CMDBError


class TestBulkCreate:
    def test_bulk_create_basic(self, client: CMDBClient):
        items = [
            {"name": f"bulk-ci-{i}", "type": "server", "attributes": {"source": "scanner"}}
            for i in range(5)
        ]
        created = client.bulk_create_cis(items)
        try:
            assert len(created) == 5
            ids = [ci.id for ci in created]
            assert len(set(ids)) == 5, "All IDs must be unique"
        finally:
            for ci in created:
                try:
                    client.delete_ci(ci.id)
                except Exception:
                    pass

    def test_bulk_created_cis_are_retrievable(self, client: CMDBClient):
        items = [
            {"name": "bulk-retrieve-1", "type": "vm"},
            {"name": "bulk-retrieve-2", "type": "container"},
        ]
        created = client.bulk_create_cis(items)
        try:
            for ci in created:
                fetched = client.get_ci(ci.id)
                assert fetched.name == ci.name
                assert fetched.type == ci.type
        finally:
            for ci in created:
                try:
                    client.delete_ci(ci.id)
                except Exception:
                    pass

    def test_empty_bulk_returns_empty(self, client: CMDBClient):
        created = client.bulk_create_cis([])
        assert created == []

    def test_bulk_preserves_source_metadata(self, client: CMDBClient):
        items = [
            {
                "name": "discovered-ec2",
                "type": "vm",
                "attributes": {
                    "source": "aws:ec2",
                    "region": "us-east-1",
                    "instance_id": "i-0abc123",
                },
            },
        ]
        created = client.bulk_create_cis(items)
        try:
            fetched = client.get_ci(created[0].id)
            assert fetched.attributes["source"] == "aws:ec2"
            assert fetched.attributes["instance_id"] == "i-0abc123"
        finally:
            client.delete_ci(created[0].id)


class TestBulkScale:
    @settings(max_examples=5, suppress_health_check=[HealthCheck.too_slow])
    @given(st.integers(min_value=10, max_value=100))
    def test_bulk_at_scale(self, client: CMDBClient, count: int):
        items = [
            {"name": f"scale-ci-{i}", "type": "server"}
            for i in range(count)
        ]
        created = client.bulk_create_cis(items)
        try:
            assert len(created) == count
        finally:
            for ci in created:
                try:
                    client.delete_ci(ci.id)
                except Exception:
                    pass

    def test_bulk_100_appears_in_list(self, client: CMDBClient):
        items = [
            {"name": f"list-bulk-{i}", "type": "bulk_test"}
            for i in range(100)
        ]
        created = client.bulk_create_cis(items)
        try:
            listed, total = client.list_cis(type="bulk_test")
            created_ids = {ci.id for ci in created}
            listed_ids = {ci.id for ci in listed}
            assert created_ids.issubset(listed_ids) or total >= 100
        finally:
            for ci in created:
                try:
                    client.delete_ci(ci.id)
                except Exception:
                    pass


class TestBulkValidation:
    def test_all_invalid_items_rejected(self, client: CMDBClient):
        """A batch of entirely invalid CIs should fail."""
        items = [
            {"name": "", "type": ""},  # empty required fields
            {"type": "server"},  # missing name
        ]
        with pytest.raises(CMDBError) as exc:
            client.bulk_create_cis(items)
        assert exc.value.status_code in (400, 422)

    def test_bulk_with_duplicate_names_succeeds(self, client: CMDBClient):
        """Duplicate names in a batch are allowed — each gets a unique ID."""
        items = [
            {"name": "same-name", "type": "server"},
            {"name": "same-name", "type": "server"},
        ]
        created = client.bulk_create_cis(items)
        try:
            assert len(created) == 2
            assert created[0].id != created[1].id
        finally:
            for ci in created:
                try:
                    client.delete_ci(ci.id)
                except Exception:
                    pass
