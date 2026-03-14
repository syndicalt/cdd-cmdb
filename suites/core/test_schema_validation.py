"""Schema validation tests.

The CMDB must enforce the CI input schema at the API boundary:
- name and type are required fields
- Empty name must be rejected
- Scalar attribute values (str, int, float, bool, null) are accepted
- Nested objects as attribute values must be rejected (non-scalar)
- Each create call returns a distinct ID (no deduplication on name)
"""
from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from harness.client import CMDBClient


class TestRequiredFields:
    def test_missing_name_rejected(self, client: CMDBClient):
        resp = client.raw_post("/cis", {"type": "server"})
        assert resp.status_code in (400, 422), (
            f"Expected 400/422 for missing name, got {resp.status_code}"
        )

    def test_missing_type_rejected(self, client: CMDBClient):
        resp = client.raw_post("/cis", {"name": "my-ci"})
        assert resp.status_code in (400, 422), (
            f"Expected 400/422 for missing type, got {resp.status_code}"
        )

    def test_empty_name_rejected(self, client: CMDBClient):
        resp = client.raw_post("/cis", {"name": "", "type": "server"})
        assert resp.status_code in (400, 422), (
            f"Expected 400/422 for empty name, got {resp.status_code}"
        )

    def test_empty_type_rejected(self, client: CMDBClient):
        resp = client.raw_post("/cis", {"name": "my-ci", "type": ""})
        assert resp.status_code in (400, 422), (
            f"Expected 400/422 for empty type, got {resp.status_code}"
        )

    def test_null_name_rejected(self, client: CMDBClient):
        resp = client.raw_post("/cis", {"name": None, "type": "server"})
        assert resp.status_code in (400, 422)

    def test_null_type_rejected(self, client: CMDBClient):
        resp = client.raw_post("/cis", {"name": "my-ci", "type": None})
        assert resp.status_code in (400, 422)


class TestAttributeTypes:
    @given(st.integers(min_value=-(2**31), max_value=2**31 - 1))
    def test_integer_attribute_round_trips(self, client: CMDBClient, value: int):
        ci = client.create_ci(name="int-attr-test", type="server", attributes={"count": value})
        try:
            assert client.get_ci(ci.id).attributes["count"] == value
        finally:
            client.delete_ci(ci.id)

    @given(st.text(min_size=1, max_size=64))
    def test_string_attribute_round_trips(self, client: CMDBClient, value: str):
        ci = client.create_ci(name="str-attr-test", type="server", attributes={"label": value})
        try:
            assert client.get_ci(ci.id).attributes["label"] == value
        finally:
            client.delete_ci(ci.id)

    @given(st.booleans())
    def test_boolean_attribute_round_trips(self, client: CMDBClient, value: bool):
        ci = client.create_ci(name="bool-attr-test", type="server", attributes={"active": value})
        try:
            assert client.get_ci(ci.id).attributes["active"] == value
        finally:
            client.delete_ci(ci.id)

    def test_null_attribute_accepted(self, client: CMDBClient):
        ci = client.create_ci(name="null-attr-test", type="server", attributes={"owner": None})
        try:
            assert client.get_ci(ci.id).attributes.get("owner") is None
        finally:
            client.delete_ci(ci.id)

    def test_nested_object_attribute_rejected(self, client: CMDBClient):
        resp = client.raw_post("/cis", {
            "name": "nested-attr-test",
            "type": "server",
            "attributes": {"config": {"key": "value"}},
        })
        assert resp.status_code in (400, 422), (
            f"Nested object in attributes must be rejected; got {resp.status_code}"
        )

    def test_list_attribute_rejected(self, client: CMDBClient):
        resp = client.raw_post("/cis", {
            "name": "list-attr-test",
            "type": "server",
            "attributes": {"tags": ["a", "b"]},
        })
        assert resp.status_code in (400, 422), (
            f"List value in attributes must be rejected; got {resp.status_code}"
        )


class TestIdempotency:
    def test_same_name_gets_distinct_ids(self, client: CMDBClient):
        ci1 = client.create_ci(name="duplicate-name", type="server")
        ci2 = client.create_ci(name="duplicate-name", type="server")
        try:
            assert ci1.id != ci2.id, "Each create must return a unique ID"
        finally:
            client.delete_ci(ci1.id)
            client.delete_ci(ci2.id)
