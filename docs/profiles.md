---
layout: default
title: Profiles
---

# Profiles

Profiles are compliance tiers. Each one is a pytest `.ini` file in `profiles/` that selects which test suites to run.

## Available Profiles

### Minimal

**File:** `profiles/minimal.ini`
**Suites:** `core/`

The entry-level bar. Any CMDB implementation must pass this before anything else. Covers:

- CI CRUD (create, read, update, delete)
- Relationship management (create, query by direction, delete)
- Schema validation (required fields, scalar-only attributes)
- Referential integrity (can't delete a CI with active relationships)

```bash
CMDB_BASE_URL=http://localhost:8080 pytest -c profiles/minimal.ini
```

### Standard

**File:** `profiles/standard.ini`
**Suites:** `core/`, `discovery/`, `audit/`, `graph/`

Production-grade. Adds the capabilities that differentiate a CMDB from a key-value store:

- **Discovery:** Bulk CI import with source metadata tracking
- **Audit:** Immutable change history for every CI
- **Graph:** Multi-hop impact analysis and dependency traversal, cycle safety

```bash
CMDB_BASE_URL=http://localhost:8080 pytest -c profiles/standard.ini
```

### Enterprise

**File:** `profiles/enterprise.ini`
**Suites:** all

Full compliance. Everything in standard, plus:

- **Security:** Injection resistance (SQL, XSS, NoSQL, template injection, path traversal) across all input fields. Auth enforcement and RBAC (when configured).
- **Performance:** Latency SLAs per operation, throughput benchmarks for bulk workloads.
- **Governance:** Runtime validation policies — required attributes, allowed values, type-scoped enforcement.

```bash
CMDB_BASE_URL=http://localhost:8080 pytest -c profiles/enterprise.ini
```

## Choosing a Profile

| You want to... | Use |
|---|---|
| Validate a new implementation quickly | `minimal` |
| Ship to production | `standard` |
| Meet compliance/security requirements | `enterprise` |
| Generate with the AI generator (fast) | `minimal` |
| Generate with the AI generator (full) | `enterprise` + `--model claude-opus-4-6` |

## Conditional Tests Within Profiles

Some tests within the enterprise profile are conditionally skipped based on environment variables:

- **Auth tests** (`suites/security/test_auth.py`) — Skipped unless `CMDB_AUTH_ENABLED=true`. Auth mechanisms vary between implementations, so these tests verify enforcement rather than a specific scheme.
- **RBAC tests** — Skipped unless `CMDB_READONLY_TOKEN` is set.

## Performance SLA Configuration

The performance suite uses environment variables for thresholds, so the same tests work across different deployment tiers:

```bash
# Tighter SLAs for a high-performance deployment
CMDB_SLA_CRUD_MS=100 \
CMDB_SLA_LIST_MS=250 \
CMDB_SLA_BULK_100_MS=2000 \
CMDB_BASE_URL=http://localhost:8080 \
pytest -c profiles/enterprise.ini
```

## Creating Custom Profiles

You can create your own profile by adding a `.ini` file:

```ini
# profiles/ci.ini
[pytest]
# CI pipeline: core + security, skip performance (too flaky in CI)
testpaths = suites/core suites/security
addopts = --tb=short -q -x
```

The `-x` flag stops on the first failure, useful for fast feedback in CI pipelines.

## Hypothesis Profile Interaction

The pytest profile (which suites to run) is independent of the Hypothesis profile (how many examples per property test):

```bash
# Standard suites, thorough property testing
HYPOTHESIS_PROFILE=release \
CMDB_BASE_URL=http://localhost:8080 \
pytest -c profiles/standard.ini
```

- `ci` profile: 25 examples per `@given` test (default, ~seconds)
- `release` profile: 500 examples per `@given` test (~minutes)
