"""Input sanitization and injection resistance tests.

The CMDB must not crash, execute injected code, or return unescaped
payloads regardless of what is sent in CI names, types, or attributes.
These tests do not require auth — they verify boundary safety.

Invariants:
- No input string causes a 500 Internal Server Error
- SQL/NoSQL injection payloads are treated as literal data
- HTML/script payloads are stored and returned without execution context
- Malformed JSON is rejected with 400, not a crash
"""
from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from harness.client import CMDBClient, CMDBError

# Classic injection payloads — not exhaustive, but catches common failures
SQL_PAYLOADS = [
    "'; DROP TABLE cis; --",
    "1 OR 1=1",
    "' UNION SELECT * FROM users --",
    "1; EXEC xp_cmdshell('whoami')",
    "' OR ''='",
    "Robert'); DROP TABLE students;--",
]

NOSQL_PAYLOADS = [
    '{"$gt": ""}',
    '{"$ne": null}',
    '{"$where": "sleep(5000)"}',
]

XSS_PAYLOADS = [
    '<script>alert("xss")</script>',
    '"><img src=x onerror=alert(1)>',
    "javascript:alert(1)",
    '<svg onload=alert(1)>',
]

TEMPLATE_INJECTION_PAYLOADS = [
    "{{7*7}}",
    "${7*7}",
    "<%= 7*7 %>",
    "#{7*7}",
]

PATH_TRAVERSAL_PAYLOADS = [
    "../../etc/passwd",
    "..\\..\\windows\\system32",
    "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
]

ALL_PAYLOADS = (
    SQL_PAYLOADS
    + NOSQL_PAYLOADS
    + XSS_PAYLOADS
    + TEMPLATE_INJECTION_PAYLOADS
    + PATH_TRAVERSAL_PAYLOADS
)


class TestNameInjection:
    @pytest.mark.parametrize("payload", ALL_PAYLOADS)
    def test_injection_in_name_does_not_crash(self, client: CMDBClient, payload: str):
        """Injected name must be stored literally or rejected — never cause 500."""
        try:
            ci = client.create_ci(name=payload, type="server")
            # If accepted, the value must round-trip exactly
            fetched = client.get_ci(ci.id)
            assert fetched.name == payload
            client.delete_ci(ci.id)
        except CMDBError as e:
            assert e.status_code != 500, f"Injection payload caused 500: {payload!r}"

    @given(st.text(min_size=1, max_size=256))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_fuzz_name(self, client: CMDBClient, name: str):
        """No arbitrary string in name should produce a server error."""
        try:
            ci = client.create_ci(name=name, type="server")
            client.delete_ci(ci.id)
        except CMDBError as e:
            assert e.status_code < 500, f"Server error for name={name!r}: {e}"


class TestTypeInjection:
    @pytest.mark.parametrize("payload", ALL_PAYLOADS)
    def test_injection_in_type_does_not_crash(self, client: CMDBClient, payload: str):
        try:
            ci = client.create_ci(name="injection-type-test", type=payload)
            fetched = client.get_ci(ci.id)
            assert fetched.type == payload
            client.delete_ci(ci.id)
        except CMDBError as e:
            assert e.status_code != 500, f"Injection payload caused 500: {payload!r}"


class TestAttributeInjection:
    @pytest.mark.parametrize("payload", ALL_PAYLOADS)
    def test_injection_in_attribute_key(self, client: CMDBClient, payload: str):
        try:
            ci = client.create_ci(
                name="attr-key-inject", type="server", attributes={payload: "value"}
            )
            fetched = client.get_ci(ci.id)
            assert fetched.attributes.get(payload) == "value"
            client.delete_ci(ci.id)
        except CMDBError as e:
            assert e.status_code != 500

    @pytest.mark.parametrize("payload", ALL_PAYLOADS)
    def test_injection_in_attribute_value(self, client: CMDBClient, payload: str):
        try:
            ci = client.create_ci(
                name="attr-val-inject", type="server", attributes={"data": payload}
            )
            fetched = client.get_ci(ci.id)
            assert fetched.attributes["data"] == payload
            client.delete_ci(ci.id)
        except CMDBError as e:
            assert e.status_code != 500


class TestQueryInjection:
    @pytest.mark.parametrize("payload", SQL_PAYLOADS + NOSQL_PAYLOADS)
    def test_injection_in_list_filter(self, client: CMDBClient, payload: str):
        """Injection in query parameters must not crash or leak data."""
        try:
            items, _ = client.list_cis(type=payload)
            # Should return empty or matching — never crash
        except CMDBError as e:
            assert e.status_code < 500


class TestMalformedInput:
    def test_empty_body_rejected(self, client: CMDBClient):
        resp = client.raw_post("/cis", {})
        assert resp.status_code in (400, 422)

    def test_array_body_rejected(self, client: CMDBClient):
        headers = {"content-type": "application/json"}
        resp = client._http.post("/cis", content=b"[]", headers=headers)
        assert resp.status_code in (400, 422)

    def test_non_json_body_rejected(self, client: CMDBClient):
        headers = {"content-type": "application/json"}
        resp = client._http.post(
            "/cis", content=b"not json", headers=headers,
        )
        assert resp.status_code in (400, 422)

    def test_extremely_long_name(self, client: CMDBClient):
        """Names over a reasonable length must be rejected or truncated, not crash."""
        long_name = "a" * 10_000
        try:
            ci = client.create_ci(name=long_name, type="server")
            client.delete_ci(ci.id)
        except CMDBError as e:
            assert e.status_code < 500

    def test_null_byte_in_name(self, client: CMDBClient):
        try:
            ci = client.create_ci(name="test\x00injection", type="server")
            client.delete_ci(ci.id)
        except CMDBError as e:
            assert e.status_code < 500
