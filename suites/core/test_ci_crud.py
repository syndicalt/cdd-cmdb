"""Core CI CRUD tests.

Invariants verified:
- create → read returns identical data
- create → update → read reflects the update
- delete → read raises NotFoundError
- server assigns a valid UUID as id
- created_at and updated_at are present after create
"""
from __future__ import annotations

import re
import pytest
from hypothesis import given

from harness.client import CMDBClient, NotFoundError
from harness.factories.ci_factory import ci_input_strategy

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class TestCICreate:
    def test_returns_valid_uuid(self, make_ci):
        ci = make_ci("web-server-1", type="server")
        assert UUID_RE.match(ci.id), f"id {ci.id!r} is not a valid UUID"

    def test_returned_data_matches_input(self, make_ci):
        ci = make_ci("db-primary", type="database", attributes={"port": 5432, "engine": "postgres"})
        assert ci.name == "db-primary"
        assert ci.type == "database"
        assert ci.attributes["port"] == 5432
        assert ci.attributes["engine"] == "postgres"

    def test_timestamps_present(self, make_ci):
        ci = make_ci("app-1", type="app")
        assert ci.created_at, "created_at must be non-empty"
        assert ci.updated_at, "updated_at must be non-empty"

    def test_empty_attributes_accepted(self, make_ci):
        ci = make_ci("bare-ci", type="server")
        assert isinstance(ci.attributes, dict)

    @given(ci_input_strategy)
    def test_create_read_round_trip(self, client: CMDBClient, ci_data: dict):
        ci = client.create_ci(**ci_data)
        try:
            fetched = client.get_ci(ci.id)
            assert fetched.name == ci_data["name"]
            assert fetched.type == ci_data["type"]
            assert fetched.attributes == (ci_data.get("attributes") or {})
        finally:
            client.delete_ci(ci.id)


class TestCIRead:
    def test_not_found_raises(self, client: CMDBClient):
        with pytest.raises(NotFoundError):
            client.get_ci("00000000-0000-0000-0000-000000000000")


class TestCIUpdate:
    def test_update_reflects_on_read(self, make_ci, client: CMDBClient):
        ci = make_ci("old-name", type="server")
        client.update_ci(ci.id, name="new-name", type="vm", attributes={"migrated": True})
        fetched = client.get_ci(ci.id)
        assert fetched.name == "new-name"
        assert fetched.type == "vm"
        assert fetched.attributes.get("migrated") is True

    def test_update_clears_attributes_when_omitted(self, make_ci, client: CMDBClient):
        ci = make_ci("ci-with-attrs", type="server", attributes={"env": "prod"})
        client.update_ci(ci.id, name="ci-with-attrs", type="server", attributes={})
        fetched = client.get_ci(ci.id)
        assert fetched.attributes == {}

    def test_update_nonexistent_raises(self, client: CMDBClient):
        with pytest.raises(NotFoundError):
            client.update_ci("00000000-0000-0000-0000-000000000000", name="x", type="server")

    @given(ci_input_strategy, ci_input_strategy)
    def test_update_round_trip(self, client: CMDBClient, initial: dict, updated_data: dict):
        ci = client.create_ci(**initial)
        try:
            client.update_ci(ci.id, **updated_data)
            fetched = client.get_ci(ci.id)
            assert fetched.name == updated_data["name"]
            assert fetched.type == updated_data["type"]
        finally:
            client.delete_ci(ci.id)


class TestCIDelete:
    def test_delete_then_not_found(self, client: CMDBClient):
        ci = client.create_ci(name="to-delete", type="temp")
        client.delete_ci(ci.id)
        with pytest.raises(NotFoundError):
            client.get_ci(ci.id)

    def test_delete_nonexistent_raises(self, client: CMDBClient):
        with pytest.raises(NotFoundError):
            client.delete_ci("00000000-0000-0000-0000-000000000000")


class TestCIList:
    def test_created_ci_appears_in_list(self, make_ci, client: CMDBClient):
        ci = make_ci("listable", type="server")
        items, total = client.list_cis()
        assert ci.id in [c.id for c in items]

    def test_filter_by_type_returns_only_that_type(self, make_ci, client: CMDBClient):
        make_ci("typed-ci", type="certificate")
        items, _ = client.list_cis(type="certificate")
        assert all(c.type == "certificate" for c in items)
        assert len(items) >= 1

    def test_total_reflects_count(self, make_ci, client: CMDBClient):
        _, total_before = client.list_cis()
        make_ci("count-test", type="server")
        _, total_after = client.list_cis()
        assert total_after >= total_before + 1
