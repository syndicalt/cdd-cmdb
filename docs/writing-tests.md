# Writing Tests

This guide covers how to add new test suites to the CDD-CMDB specification.

## The Cardinal Rule

**No test may import implementation code.** All interaction with the CMDB goes through `harness/client.py`. This is what makes the spec implementation-agnostic. A test that imports Flask models or SQLAlchemy schemas is broken by design.

## Anatomy of a Test

```python
# suites/core/test_ci_crud.py

from harness.client import CMDBClient, NotFoundError

class TestCIDelete:
    def test_delete_then_not_found(self, client: CMDBClient):
        ci = client.create_ci(name="to-delete", type="temp")
        client.delete_ci(ci.id)
        with pytest.raises(NotFoundError):
            client.get_ci(ci.id)
```

Key elements:
- **`client` fixture** — injected by `conftest.py`, session-scoped
- **Typed exceptions** — assert on `NotFoundError`, not `status_code == 404`
- **Self-contained** — the test creates its own data and cleans up

## Using Factory Fixtures

For tests that need CIs or relationships, use the `make_ci` and `make_relationship` fixtures. They auto-delete after the test:

```python
class TestSomething:
    def test_with_fixtures(self, make_ci, make_relationship, client: CMDBClient):
        server = make_ci("web-1", type="server")
        app = make_ci("app-1", type="app")
        rel = make_relationship(server.id, app.id, type="hosts")
        # No cleanup needed — fixtures handle it
```

## Property-Based Tests

Use Hypothesis for invariants that should hold for any valid input:

```python
from hypothesis import given
from harness.factories.ci_factory import ci_input_strategy

class TestCICreate:
    @given(ci_input_strategy)
    def test_create_read_round_trip(self, client: CMDBClient, ci_data: dict):
        ci = client.create_ci(**ci_data)
        try:
            fetched = client.get_ci(ci.id)
            assert fetched.name == ci_data["name"]
        finally:
            client.delete_ci(ci.id)
```

Important: `@given` tests **must do their own cleanup** in `finally` blocks. Hypothesis runs multiple examples within a single pytest invocation, so the `make_ci` fixture teardown timing doesn't apply.

### Adding New Strategies

Define reusable strategies in `harness/factories/ci_factory.py`:

```python
from hypothesis import strategies as st

my_strategy = st.fixed_dictionaries({
    "name": safe_text,
    "type": st.sampled_from(["server", "app", "database"]),
})
```

## Negative / Validation Tests

For tests that send intentionally invalid payloads, use `client.raw_post()` or `client.raw_request()` to avoid the automatic error-raising:

```python
class TestValidation:
    def test_missing_name_rejected(self, client: CMDBClient):
        resp = client.raw_post("/cis", {"type": "server"})
        assert resp.status_code in (400, 422)
```

Accept multiple valid status codes (e.g., `400` or `422`) — the spec cares that bad input is rejected, not which specific 4xx code the implementation chooses.

## Adding a New API Surface

When your tests define new endpoints:

1. **Add client methods** in `harness/client.py`:
   ```python
   def my_new_endpoint(self, ...) -> SomeModel:
       resp = self._http.get("/new-endpoint", ...)
       _raise(resp)
       return SomeModel.from_dict(resp.json())
   ```

2. **Add response models** as `@dataclass` classes with a `from_dict` classmethod.

3. **Add factory fixtures** in `conftest.py` if tests need setup/teardown helpers.

4. **Update the OpenAPI spec** in `specs/openapi/cmdb.yaml` to document the endpoint contract.

5. **Add the new suite** to the appropriate profile(s) in `profiles/`.

## Organizing Suites

Each suite directory covers a distinct CMDB capability:

```
suites/
  core/           # Foundation: CRUD, relationships, schema validation
  security/       # Boundary protection: injection, auth, RBAC
  discovery/      # Bulk import, source tracking
  performance/    # Latency and throughput SLAs
  governance/     # Runtime validation policies
  audit/          # Immutable change history
  graph/          # Multi-hop traversal, impact analysis
```

To add a new suite:
1. Create `suites/my_suite/__init__.py`
2. Add test files as `suites/my_suite/test_*.py`
3. Add the suite to the relevant profile(s) in `profiles/`

## Test Docstrings

Each test file should have a module-level docstring listing the invariants it verifies. This serves two purposes:
- Documentation for humans reading the spec
- Context for the generator when it produces implementations

```python
"""Relationship management tests.

Invariants verified:
- Relationship requires both source and target CIs to exist
- Deleting a CI with active relationships raises 409 Conflict
- Direction filtering (inbound/outbound/both) works correctly
"""
```

## Performance Tests

Performance tests define SLAs via environment variables with conservative defaults:

```python
SLA_CRUD_MS = int(os.environ.get("CMDB_SLA_CRUD_MS", "500"))

class TestLatency:
    def test_read_within_sla(self, make_ci, client):
        ci = make_ci("perf-test", type="server")
        start = time.monotonic()
        client.get_ci(ci.id)
        ms = (time.monotonic() - start) * 1000
        assert ms < SLA_CRUD_MS
```

Always use `time.monotonic()` over `time.time()` for timing.
