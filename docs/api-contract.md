# API Contract

The full API surface is defined by the OpenAPI spec at `specs/openapi/cmdb.yaml` and extended by the test suites. This document summarizes the contract.

## Data Model

### Configuration Item (CI)

A CI represents any managed resource: servers, applications, databases, network devices, certificates, containers, etc.

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "prod-web-1",
  "type": "server",
  "attributes": {
    "env": "production",
    "region": "us-east-1",
    "owner": "platform-team",
    "port": 443
  },
  "created_at": "2026-01-15T10:30:00Z",
  "updated_at": "2026-03-01T14:22:00Z"
}
```

- `id` — UUID, assigned by the server on creation
- `name` — non-empty string, not unique (multiple CIs can share a name)
- `type` — non-empty string label (not an enum — any string is valid)
- `attributes` — flat key-value map of **scalars only** (string, number, boolean, null). Nested objects and arrays are rejected with 400/422
- `created_at`, `updated_at` — ISO 8601 timestamps, server-managed

### Relationship

A directed, typed edge between two CIs.

```json
{
  "id": "660e8400-e29b-41d4-a716-446655440000",
  "source_id": "550e8400-...",
  "target_id": "770e8400-...",
  "type": "hosts",
  "attributes": {},
  "created_at": "2026-02-10T08:00:00Z"
}
```

Common relationship types: `hosts`, `depends_on`, `connects_to`, `monitors`, `backs_up`, `load_balances`, `contains`, `replicates_to`, `managed_by`.

### Policy

A runtime validation rule applied to CIs of a specific type.

```json
{
  "id": "880e8400-...",
  "ci_type": "server",
  "rules": {
    "required_attributes": ["owner", "env"],
    "allowed_values": {
      "env": ["prod", "staging", "dev"]
    }
  },
  "created_at": "2026-03-10T12:00:00Z"
}
```

### Audit Entry

An immutable record of a change to a CI.

```json
{
  "id": "990e8400-...",
  "ci_id": "550e8400-...",
  "action": "updated",
  "changes": {"name": {"old": "web-1", "new": "web-1-v2"}},
  "timestamp": "2026-03-01T14:22:00Z",
  "actor": "api-key-abc123"
}
```

## Endpoints

### Health

| Method | Path | Response |
|---|---|---|
| `GET` | `/health` | `{"status": "ok"}` |

### Configuration Items

| Method | Path | Request | Response | Notes |
|---|---|---|---|---|
| `POST` | `/cis` | `CIInput` | `201 CI` | Enforces active policies |
| `GET` | `/cis` | query: `type`, `name`, `limit`, `offset` | `{"items": [CI], "total": int}` | |
| `GET` | `/cis/{id}` | — | `200 CI` or `404` | |
| `PUT` | `/cis/{id}` | `CIInput` | `200 CI` or `404` | Full replacement |
| `DELETE` | `/cis/{id}` | — | `204` or `404` or `409` | 409 if relationships exist |
| `POST` | `/cis/bulk` | `{"items": [CIInput]}` | `{"items": [CI]}` | Batch creation |
| `GET` | `/cis/{id}/history` | — | `{"items": [AuditEntry]}` | Chronological, immutable |
| `GET` | `/cis/{id}/relationships` | query: `direction`, `type` | `{"items": [Relationship]}` | direction: outbound/inbound/both |
| `GET` | `/cis/{id}/impact` | query: `depth`, `relationship_types` | `{"items": [CI]}` | Transitive outbound traversal |
| `GET` | `/cis/{id}/dependencies` | query: `depth`, `relationship_types` | `{"items": [CI]}` | Transitive inbound traversal |

### Relationships

| Method | Path | Request | Response | Notes |
|---|---|---|---|---|
| `POST` | `/relationships` | `RelationshipInput` | `201 Relationship` | Both CIs must exist |
| `GET` | `/relationships/{id}` | — | `200 Relationship` or `404` | |
| `DELETE` | `/relationships/{id}` | — | `204` or `404` | |

### Policies

| Method | Path | Request | Response |
|---|---|---|---|
| `POST` | `/policies` | `{"ci_type": str, "rules": {...}}` | `201 Policy` |
| `GET` | `/policies` | — | `{"items": [Policy]}` |
| `DELETE` | `/policies/{id}` | — | `204` or `404` |

## Behavioral Invariants

These are enforced by the test suites and must hold for any compliant implementation:

### Core
- Every `POST /cis` returns a server-assigned UUID
- `created_at` and `updated_at` are always present on CIs
- `DELETE /cis/{id}` on a nonexistent CI returns 404
- Duplicate names are allowed — each create returns a unique ID

### Relationships
- Both `source_id` and `target_id` must reference existing CIs
- Deleting a CI with active relationships returns **409 Conflict**
- Remove the relationships first, then delete the CI
- Direction filtering: `outbound` = relationships where CI is the source; `inbound` = target; `both` = either

### Schema Validation
- `name` and `type` are required, non-empty strings
- `attributes` values must be scalars — nested objects and arrays are rejected (400/422)
- `null` is a valid attribute value

### Graph Traversal
- `impact` follows outbound relationships transitively
- `dependencies` follows inbound relationships transitively
- `depth` parameter limits the number of hops
- Cycles must not cause infinite loops — visited nodes are skipped
- The root CI is **never** included in its own impact/dependency results
- `relationship_types` filter narrows which edges are traversed

### Audit
- Every create, update, and delete produces an audit entry
- History is append-only and chronological
- History survives CI deletion (the entries remain accessible)
- Entries cannot be modified or removed

### Governance
- Policies are enforced on `POST /cis` and `PUT /cis/{id}` for the matching `ci_type`
- Policies do not affect other CI types
- Existing CIs are not retroactively invalidated when a policy is created
- Removing a policy lifts the constraint immediately

### Security
- No input string (including injection payloads) may cause a 500 error
- If auth is enabled, unauthenticated requests return 401
- Auth credentials must never be echoed in response bodies

### Performance
- Single CRUD operations: < 500ms (configurable via `CMDB_SLA_CRUD_MS`)
- List queries: < 1000ms
- Health check: < 200ms
- Bulk create of 100 CIs: < 5000ms
