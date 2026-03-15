---
layout: default
title: Getting Started
---

# Getting Started

## Prerequisites

- Python 3.12+
- pip
- An `ANTHROPIC_API_KEY` (only if using the generator)

## Installation

```bash
git clone <repo-url>
cd cdd-cmdb

# For running tests only
pip install -e "."

# For running tests + using the generator
pip install -e ".[generator]"
```

## Option A: Validate an Existing Implementation

If you already have a CMDB server running, point the test suite at it:

```bash
CMDB_BASE_URL=http://localhost:8080 pytest -c profiles/minimal.ini
```

The test suite will exercise your API and report which behaviors pass or fail. The `minimal` profile covers the foundational CRUD operations — start there and work up to `standard` and `enterprise`.

## Option B: Generate a New Implementation

If you don't have an implementation yet, the generator will create one:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python -m generator --profile minimal
```

This will:
1. Read the full specification (OpenAPI, schemas, tests)
2. Ask Claude to generate a FastAPI + SQLite server
3. Install it in `./generated/.venv`
4. Start the server and run the test suite
5. Iterate on failures until all tests pass

The output lands in `./generated/` by default. You can customize:

```bash
python -m generator \
  --profile standard \
  --backend python/flask/postgres \
  --output ./my-cmdb \
  --port 9000 \
  --model claude-opus-4-6 \
  --max-iterations 10
```

## Running Tests

### Full profile

```bash
CMDB_BASE_URL=http://localhost:8080 pytest -c profiles/minimal.ini
CMDB_BASE_URL=http://localhost:8080 pytest -c profiles/standard.ini
CMDB_BASE_URL=http://localhost:8080 pytest -c profiles/enterprise.ini
```

### Single suite

```bash
CMDB_BASE_URL=http://localhost:8080 pytest suites/core/
CMDB_BASE_URL=http://localhost:8080 pytest suites/graph/
```

### Single test

```bash
CMDB_BASE_URL=http://localhost:8080 pytest suites/core/test_ci_crud.py::TestCICreate::test_returns_valid_uuid
```

### Thorough property-based testing

By default, Hypothesis runs 25 examples per property test. For release validation:

```bash
HYPOTHESIS_PROFILE=release CMDB_BASE_URL=http://localhost:8080 pytest -c profiles/enterprise.ini
```

This runs 500 examples per property, catching edge cases that fast runs miss.

## Next Steps

- [Writing Tests](writing-tests.md) — how to add new test suites
- [API Contract](api-contract.md) — the full API surface defined by the spec
- [Generator](generator.md) — how the generate-test-fix loop works
- [Profiles](profiles.md) — understanding compliance tiers
