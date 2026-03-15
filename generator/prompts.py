"""Prompt templates for CMDB generation and fix iterations."""

SYSTEM_PROMPT = """\
You are a senior backend engineer generating a complete, runnable CMDB API server.

The CMDB is defined by a test suite — your implementation must pass every test.
You are given the OpenAPI spec, JSON schemas, the test harness client code,
and the full test suite source. Study the test assertions carefully; they are
the authoritative specification.

## Constraints
- Backend stack: {backend}
- The server MUST listen on 0.0.0.0 port {port}
- The entry point MUST be `{entry_point}` — startable directly
- All dependencies MUST be listed in `{deps_file}`
- Use an in-process database (SQLite) unless the backend spec says otherwise
- Do NOT generate pytest.ini, conftest.py, setup.cfg, or pyproject.toml — those belong to the test repo
- Only generate {entry_point}, {deps_file}, and any helper modules your implementation needs
{extra_constraints}

## Output format
Output each file wrapped in <file> tags:

<file path="{deps_file}">
dependency1
dependency2
</file>

<file path="{entry_point}">
# main application code
</file>

You may create as many files as needed, but `{entry_point}` must be the entry point
and `{deps_file}` must list all dependencies.

Generate the COMPLETE implementation. Do not leave placeholders or TODOs.
"""

GENERATE_PROMPT = """\
Generate a CMDB API server that passes the following test suite.

## OpenAPI Specification
```yaml
{openapi_spec}
```

## JSON Schemas
{json_schemas}

## Test Harness (client code your server will be tested against)
{harness_code}

## Test Suite (your implementation MUST pass all of these)
{test_suites}

## Key behaviors to get right
1. All IDs must be UUIDs assigned by the server
2. created_at / updated_at must be ISO 8601 timestamps
3. CI attributes are flat scalar key-value maps — reject nested objects and arrays with 400/422
4. Deleting a CI that has relationships must return 409 Conflict
5. GET /cis/{{id}}/history must return an immutable audit trail (create/update/delete events)
6. GET /cis/{{id}}/impact traverses outbound relationships transitively; depth param limits hops
7. GET /cis/{{id}}/dependencies traverses inbound relationships transitively
8. Cycles in the graph must not cause infinite loops
9. The root CI must NOT appear in its own impact/dependency results
10. POST /policies creates runtime validation rules; POST /cis must enforce active policies
11. POST /cis/bulk accepts {{"items": [...]}} and returns {{"items": [...]}}
12. Injection payloads in names/types/attributes must be stored literally, never cause 500s

Generate all files now.
"""

FIX_PROMPT = """\
The implementation failed {failure_count} test(s). Fix the issues.

## Test output (failures only)
```
{test_output}
```

## Current implementation
{current_code}

Output ALL files in the same <file path="..."> format, even unchanged ones.
The entry point must remain the same file name.
"""
