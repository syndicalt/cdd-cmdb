"""Relationship management tests.

Invariants verified:
- Relationship requires both source and target CIs to exist
- Relationship is discoverable from both source and target via /cis/{id}/relationships
- Direction filtering (inbound/outbound/both) works correctly
- Deleting a CI that has active relationships raises 409 Conflict
- Removing the relationship first allows CI deletion
"""
from __future__ import annotations

import pytest
from hypothesis import given

from harness.client import CMDBClient, NotFoundError, ConflictError
from harness.factories.ci_factory import ci_input_strategy, relationship_type_strategy


class TestRelationshipCreate:
    def test_create_and_read(self, make_ci, client: CMDBClient):
        server = make_ci("server-1", type="server")
        app = make_ci("app-1", type="app")
        rel = client.create_relationship(server.id, app.id, type="hosts")
        try:
            fetched = client.get_relationship(rel.id)
            assert fetched.source_id == server.id
            assert fetched.target_id == app.id
            assert fetched.type == "hosts"
        finally:
            client.delete_relationship(rel.id)

    def test_nonexistent_source_raises(self, make_ci, client: CMDBClient):
        app = make_ci("app-orphan", type="app")
        with pytest.raises(Exception):  # 400 or 404 — both are compliant
            client.create_relationship("00000000-0000-0000-0000-000000000000", app.id, "hosts")

    def test_nonexistent_target_raises(self, make_ci, client: CMDBClient):
        server = make_ci("server-orphan", type="server")
        with pytest.raises(Exception):
            client.create_relationship(server.id, "00000000-0000-0000-0000-000000000000", "hosts")

    @given(ci_input_strategy, ci_input_strategy, relationship_type_strategy)
    def test_create_round_trip(
        self, client: CMDBClient, ci1_data: dict, ci2_data: dict, rel_type: str
    ):
        ci1 = client.create_ci(**ci1_data)
        ci2 = client.create_ci(**ci2_data)
        rel = client.create_relationship(ci1.id, ci2.id, type=rel_type)
        try:
            fetched = client.get_relationship(rel.id)
            assert fetched.source_id == ci1.id
            assert fetched.target_id == ci2.id
            assert fetched.type == rel_type
        finally:
            client.delete_relationship(rel.id)
            client.delete_ci(ci1.id)
            client.delete_ci(ci2.id)


class TestRelationshipDiscovery:
    def test_visible_from_source_outbound(self, make_ci, make_relationship, client: CMDBClient):
        server = make_ci("srv-out", type="server")
        app = make_ci("app-out", type="app")
        rel = make_relationship(server.id, app.id, type="hosts")
        rels = client.get_ci_relationships(server.id, direction="outbound")
        assert rel.id in [r.id for r in rels]

    def test_visible_from_target_inbound(self, make_ci, make_relationship, client: CMDBClient):
        server = make_ci("srv-in", type="server")
        app = make_ci("app-in", type="app")
        rel = make_relationship(server.id, app.id, type="hosts")
        rels = client.get_ci_relationships(app.id, direction="inbound")
        assert rel.id in [r.id for r in rels]

    def test_direction_both_includes_from_either_end(
        self, make_ci, make_relationship, client: CMDBClient
    ):
        a = make_ci("ci-a", type="server")
        b = make_ci("ci-b", type="server")
        rel = make_relationship(a.id, b.id, type="connects_to")
        for ci_id in [a.id, b.id]:
            rels = client.get_ci_relationships(ci_id, direction="both")
            assert rel.id in [r.id for r in rels]

    def test_outbound_excludes_inbound_rels(self, make_ci, make_relationship, client: CMDBClient):
        a = make_ci("ci-src", type="server")
        b = make_ci("ci-tgt", type="server")
        rel = make_relationship(a.id, b.id, type="connects_to")
        # From b's perspective outbound: rel should NOT appear
        rels = client.get_ci_relationships(b.id, direction="outbound")
        assert rel.id not in [r.id for r in rels]


class TestRelationshipIntegrity:
    def test_delete_ci_with_relationship_raises_conflict(self, make_ci, client: CMDBClient):
        server = make_ci("srv-blocked", type="server")
        app = make_ci("app-blocked", type="app")
        rel = client.create_relationship(server.id, app.id, type="hosts")
        try:
            with pytest.raises(ConflictError):
                client.delete_ci(server.id)
        finally:
            client.delete_relationship(rel.id)

    def test_delete_relationship_then_ci_succeeds(self, client: CMDBClient):
        server = client.create_ci(name="srv-cleanup", type="server")
        app = client.create_ci(name="app-cleanup", type="app")
        rel = client.create_relationship(server.id, app.id, type="hosts")
        client.delete_relationship(rel.id)
        # Now CI deletion must succeed
        client.delete_ci(server.id)
        client.delete_ci(app.id)
        with pytest.raises(NotFoundError):
            client.get_ci(server.id)

    def test_delete_relationship_then_not_found(self, make_ci, client: CMDBClient):
        a = make_ci("ci-rel-del-a", type="server")
        b = make_ci("ci-rel-del-b", type="server")
        rel = client.create_relationship(a.id, b.id, type="monitors")
        client.delete_relationship(rel.id)
        with pytest.raises(NotFoundError):
            client.get_relationship(rel.id)
