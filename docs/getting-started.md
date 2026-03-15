---
layout: default
title: Getting Started
---

# Getting Started

This tutorial walks you through running the CDD-CMDB test suite against the reference implementation, exploring the API by hand, and understanding how tests-as-specification works in practice.

**Time:** ~10 minutes
**Prerequisites:** Python 3.12+, pip, curl (or any HTTP client)

---

## Step 1: Clone and Install

```bash
git clone https://github.com/syndicalt/cdd-cmdb.git
cd cdd-cmdb
pip install -e "."
```

This installs the test harness and all test dependencies. No API keys needed.

## Step 2: Start the Reference Server

The reference implementation is a FastAPI + SQLite server committed to the repo. Start it:

```bash
PORT=9090 python reference/app.py
```

In a **second terminal**, verify it's alive:

```bash
curl http://localhost:9090/health
# → {"status": "healthy"}
```

## Step 3: Run Your First Test

Run the core CRUD suite — the foundation of the specification:

```bash
CMDB_BASE_URL=http://localhost:9090 pytest suites/core/test_ci_crud.py --tb=short -q
```

You should see all tests pass. Each test is a behavioral requirement: "creating a CI returns a valid UUID", "deleting a CI with relationships returns 409", etc.

## Step 4: Explore the API

With the server still running, try the API yourself:

**Create a CI:**
```bash
curl -s -X POST http://localhost:9090/cis \
  -H 'Content-Type: application/json' \
  -d '{"name": "web-01", "type": "server", "attributes": {"env": "prod", "region": "us-east-1"}}' | python -m json.tool
```

**List all CIs:**
```bash
curl -s http://localhost:9090/cis | python -m json.tool
```

**Create a relationship:**
```bash
# First create a second CI
curl -s -X POST http://localhost:9090/cis \
  -H 'Content-Type: application/json' \
  -d '{"name": "postgres-main", "type": "database", "attributes": {"engine": "postgresql"}}' | python -m json.tool

# Link them (replace the IDs with the ones returned above)
curl -s -X POST http://localhost:9090/relationships \
  -H 'Content-Type: application/json' \
  -d '{"source_id": "<web-01-id>", "target_id": "<postgres-main-id>", "type": "depends_on"}' | python -m json.tool
```

**Search by attribute:**
```bash
curl -s 'http://localhost:9090/cis/search?q=prod' | python -m json.tool
```

**Check audit history:**
```bash
curl -s http://localhost:9090/cis/<id>/history | python -m json.tool
```

## Step 5: Run a Full Profile

Profiles are compliance tiers. Start with minimal and work up:

```bash
# Minimal — core CRUD only
CMDB_BASE_URL=http://localhost:9090 pytest suites/core --tb=short -q

# Standard — production-grade
CMDB_BASE_URL=http://localhost:9090 pytest suites/core suites/discovery suites/audit suites/graph suites/search suites/diff suites/reconciliation suites/tags suites/ttl suites/webhooks --tb=short -q

# Enterprise — everything
CMDB_BASE_URL=http://localhost:9090 pytest suites/ --tb=short -q
```

## Step 6: Break Something

This is where CDD shines. Open `reference/app.py`, find the `delete_ci` endpoint, and comment out the relationship check:

```python
# Comment out these lines in delete_ci:
# rels = conn.execute("SELECT COUNT(*) as cnt FROM relationships ...
# if rels["cnt"] > 0:
#     raise HTTPException(status_code=409, ...)
```

Now re-run the core tests:

```bash
CMDB_BASE_URL=http://localhost:9090 pytest suites/core/test_ci_crud.py -k "delete" --tb=short -q
```

The `test_delete_ci_with_relationship_409` test fails — the specification caught the regression. Undo your change and the tests pass again. This is the feedback loop: **tests define the contract, implementations prove compliance.**

## Step 7: Use the Demo Script

For a one-command experience that handles setup, server lifecycle, and test execution:

```bash
./demo.sh                        # minimal profile
./demo.sh --profile standard     # standard profile
./demo.sh --profile enterprise   # full suite
```

The script starts the server, runs the chosen profile's tests, and leaves the server running for you to explore.

---

## Or: Use the Demo Script Directly

If you want to skip the manual steps entirely:

```bash
git clone https://github.com/syndicalt/cdd-cmdb.git && cd cdd-cmdb
./demo.sh
```

This installs dependencies, starts the reference server, runs the test suite, and reports results — all in one command.

---

## What's Next

- **Validate your own implementation:** Point `CMDB_BASE_URL` at any HTTP server and run the tests. If they pass, your server is a compliant CMDB.
- **Generate a new implementation:** Use the [generator](generator.md) to have an LLM build a passing server from scratch.
- **Add new test suites:** See [Writing Tests](writing-tests.md) to extend the specification.
- **Understand the contract:** Read the [API Contract](api-contract.md) for the full REST surface.
- **Choose a compliance tier:** See [Profiles](profiles.md) for what each tier covers.
