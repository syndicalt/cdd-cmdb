# Contributing to CDD-CMDB

Thank you for your interest in contributing to CDD-CMDB. This project is a test-suite-as-specification for a Configuration Management Database. Contributions take the form of **new or improved tests**, not implementation code.

## How to Contribute

### Adding Tests to Existing Suites

1. Find the relevant suite in `suites/` (e.g., `suites/core/`, `suites/graph/`).
2. Add test functions or classes to existing `test_*.py` files.
3. Run your tests against a compliant instance to verify they're meaningful.

### Creating a New Suite

New suites add capabilities to the CMDB specification. Follow these steps:

#### 1. Create the suite directory

```bash
mkdir suites/my_suite
touch suites/my_suite/__init__.py
```

#### 2. Write the test file

Create `suites/my_suite/test_my_feature.py`:

```python
"""My feature tests.

Invariants verified:
- List the behavioral contracts this suite enforces
- Each invariant should be independently testable
"""
from __future__ import annotations

import pytest
from harness.client import CMDBClient


class TestMyFeature:
    def test_basic_behavior(self, make_ci, client: CMDBClient):
        ci = make_ci("test-ci", type="server")
        # Test against the API, not implementation internals
        result = client.get_ci(ci.id)
        assert result.name == "test-ci"
```

#### 3. Add client methods (if new endpoints are needed)

Add methods to `harness/client.py`:

```python
def my_new_endpoint(self, ci_id: str) -> dict:
    resp = self._http.get(f"/cis/{ci_id}/my-feature")
    _raise(resp)
    return resp.json()
```

If your endpoint returns a new data type, add a `@dataclass` response model with a `from_dict` classmethod.

#### 4. Add fixtures (if needed)

Add factory fixtures to `conftest.py` for setup/teardown:

```python
@pytest.fixture
def make_my_thing(client: CMDBClient):
    created = []
    def _make(**kwargs):
        thing = client.create_my_thing(**kwargs)
        created.append(thing)
        return thing
    yield _make
    for thing in reversed(created):
        try:
            client.delete_my_thing(thing.id)
        except Exception:
            pass
```

#### 5. Add to a profile

Edit the appropriate profile in `profiles/`:

```ini
# profiles/standard.ini
[pytest]
testpaths = suites/core suites/discovery suites/audit suites/graph suites/my_suite
```

#### 6. Update the OpenAPI spec (optional but recommended)

Document new endpoints in `specs/openapi/cmdb.yaml`.

## Rules

### The Cardinal Rule

**No test may import implementation code.** All CMDB interaction goes through `harness/client.py`. This is what keeps the spec implementation-agnostic. If you find yourself importing Flask, SQLAlchemy, or any server framework in a test file, something is wrong.

### Test Style

- **Example-based tests** for specific scenarios with concrete data.
- **Property-based tests** (`@given`) for invariants that should hold for any valid input.
- **Parametrized tests** (`@pytest.mark.parametrize`) for running the same assertion across multiple inputs (e.g., injection payloads).
- `@given` tests must do their own cleanup in `finally` blocks — Hypothesis runs outside the fixture teardown lifecycle.

### Negative Tests

For tests that send intentionally invalid payloads, use `client.raw_post()` or `client.raw_request()`:

```python
def test_bad_input_rejected(self, client: CMDBClient):
    resp = client.raw_post("/cis", {"name": "", "type": ""})
    assert resp.status_code in (400, 422)
```

Accept multiple valid status codes where the spec doesn't mandate a specific one.

### Module Docstrings

Every test file must have a module-level docstring listing invariants. This serves as documentation and as context for the AI generator.

### Performance Tests

Use `time.monotonic()` for timing. Make SLA thresholds configurable via environment variables with conservative defaults:

```python
SLA_MS = int(os.environ.get("CMDB_SLA_MY_OP_MS", "500"))
```

### Conditional Tests

If a test requires specific configuration (e.g., auth enabled), skip it gracefully:

```python
pytestmark = pytest.mark.skipif(
    os.environ.get("CMDB_AUTH_ENABLED", "").lower() not in ("1", "true", "yes"),
    reason="CMDB_AUTH_ENABLED not set",
)
```

## Example: Cloud Discovery Plugin Suite

Here's a worked example of adding a cloud discovery plugin suite.

### `suites/discovery_aws/__init__.py`

```python
```

### `suites/discovery_aws/test_ec2.py`

```python
"""AWS EC2 discovery tests.

Invariants:
- POST /discover/aws/ec2 returns CIs with instance_id attributes
- Discovered CIs have source="aws:ec2" in attributes
- Invalid credentials return 401, not 500
- Discovery results are importable via POST /cis/bulk

Skipped unless CMDB_AWS_DISCOVERY=true is set.
"""
from __future__ import annotations

import os
import pytest
from harness.client import CMDBClient

pytestmark = pytest.mark.skipif(
    os.environ.get("CMDB_AWS_DISCOVERY", "").lower() not in ("1", "true"),
    reason="CMDB_AWS_DISCOVERY not set",
)


class TestEC2Discovery:
    def test_discover_returns_instances(self, client: CMDBClient):
        resp = client.raw_post("/discover/aws/ec2", {
            "region": "us-east-1",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) > 0
        assert all("instance_id" in ci["attributes"] for ci in data["items"])

    def test_discovered_cis_importable(self, client: CMDBClient):
        resp = client.raw_post("/discover/aws/ec2", {"region": "us-east-1"})
        discovered = resp.json()["items"]
        created = client.bulk_create_cis(discovered)
        try:
            assert len(created) == len(discovered)
        finally:
            for ci in created:
                try:
                    client.delete_ci(ci.id)
                except Exception:
                    pass
```

### Add to a custom profile

```ini
# profiles/aws.ini
[pytest]
testpaths = suites/core suites/discovery suites/discovery_aws
addopts = --tb=short -q
```

## Submitting Your Contribution

1. Fork the repository.
2. Create a branch: `git checkout -b add-my-suite`
3. Add your tests following the guidelines above.
4. Run the tests against a compliant CMDB instance to verify they pass.
5. Open a pull request with:
   - A description of the invariants your tests enforce
   - Which profile(s) your suite belongs to
   - Any new client methods or fixtures added

## Code of Conduct

Be respectful. Write clear tests. Ship good specs.

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.
