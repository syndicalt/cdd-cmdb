"""Graph traversal tests.

The CMDB's relationship graph must support multi-hop traversal
for impact analysis and dependency mapping.

API surface:
- GET /cis/{id}/impact        Downstream CIs affected (outbound traversal)
- GET /cis/{id}/dependencies  Upstream CIs depended on (inbound traversal)

Query parameters:
- depth                Max hops (default 3)
- relationship_types   Comma-separated filter

Invariants:
- Direct neighbors appear at depth=1
- Transitive dependencies appear at depth > 1
- Depth limit is respected — no results beyond the specified depth
- Cycles do not cause infinite loops or crashes
- The root CI is NOT included in its own impact/dependency set
- Relationship type filtering narrows the traversal
"""
from __future__ import annotations

from harness.client import CMDBClient


class TestDirectTraversal:
    def test_impact_returns_direct_dependent(self, client: CMDBClient):
        """A → B (hosts): B should appear in A's impact set."""
        a = client.create_ci(name="trav-a", type="server")
        b = client.create_ci(name="trav-b", type="app")
        rel = client.create_relationship(a.id, b.id, type="hosts")
        try:
            impact = client.get_ci_impact(a.id, depth=1)
            assert b.id in [ci.id for ci in impact]
        finally:
            client.delete_relationship(rel.id)
            client.delete_ci(a.id)
            client.delete_ci(b.id)

    def test_dependencies_returns_direct_upstream(self, client: CMDBClient):
        """A → B (depends_on): A should appear in B's dependency set."""
        a = client.create_ci(name="dep-a", type="app")
        b = client.create_ci(name="dep-b", type="database")
        rel = client.create_relationship(a.id, b.id, type="depends_on")
        try:
            deps = client.get_ci_dependencies(b.id, depth=1)
            assert a.id in [ci.id for ci in deps]
        finally:
            client.delete_relationship(rel.id)
            client.delete_ci(a.id)
            client.delete_ci(b.id)


class TestTransitiveTraversal:
    def test_two_hop_impact(self, client: CMDBClient):
        """A → B → C: C should appear in A's impact at depth >= 2."""
        a = client.create_ci(name="chain-a", type="server")
        b = client.create_ci(name="chain-b", type="app")
        c = client.create_ci(name="chain-c", type="database")
        r1 = client.create_relationship(a.id, b.id, type="hosts")
        r2 = client.create_relationship(b.id, c.id, type="connects_to")
        try:
            # Depth 1 should NOT include C
            impact_1 = client.get_ci_impact(a.id, depth=1)
            assert c.id not in [ci.id for ci in impact_1]

            # Depth 2 should include C
            impact_2 = client.get_ci_impact(a.id, depth=2)
            assert c.id in [ci.id for ci in impact_2]
        finally:
            client.delete_relationship(r1.id)
            client.delete_relationship(r2.id)
            client.delete_ci(a.id)
            client.delete_ci(b.id)
            client.delete_ci(c.id)

    def test_three_hop_chain(self, client: CMDBClient):
        """A → B → C → D: D at depth=3, not at depth=2."""
        cis = [client.create_ci(name=f"hop-{i}", type="server") for i in range(4)]
        rels = [
            client.create_relationship(cis[i].id, cis[i + 1].id, type="depends_on")
            for i in range(3)
        ]
        try:
            impact_2 = client.get_ci_impact(cis[0].id, depth=2)
            impact_3 = client.get_ci_impact(cis[0].id, depth=3)
            assert cis[3].id not in [ci.id for ci in impact_2]
            assert cis[3].id in [ci.id for ci in impact_3]
        finally:
            for rel in reversed(rels):
                client.delete_relationship(rel.id)
            for ci in reversed(cis):
                client.delete_ci(ci.id)


class TestCycleHandling:
    def test_cycle_does_not_crash(self, client: CMDBClient):
        """A → B → C → A: traversal must terminate, not loop."""
        a = client.create_ci(name="cycle-a", type="server")
        b = client.create_ci(name="cycle-b", type="server")
        c = client.create_ci(name="cycle-c", type="server")
        r1 = client.create_relationship(a.id, b.id, type="connects_to")
        r2 = client.create_relationship(b.id, c.id, type="connects_to")
        r3 = client.create_relationship(c.id, a.id, type="connects_to")
        try:
            # Must return without hanging or crashing
            impact = client.get_ci_impact(a.id, depth=10)
            # Should contain b and c (but not duplicate infinitely)
            impact_ids = [ci.id for ci in impact]
            assert b.id in impact_ids
            assert c.id in impact_ids
        finally:
            client.delete_relationship(r1.id)
            client.delete_relationship(r2.id)
            client.delete_relationship(r3.id)
            client.delete_ci(a.id)
            client.delete_ci(b.id)
            client.delete_ci(c.id)

    def test_self_loop_does_not_crash(self, client: CMDBClient):
        """A → A: self-referential relationship must not crash traversal."""
        a = client.create_ci(name="self-loop", type="server")
        r = client.create_relationship(a.id, a.id, type="monitors")
        try:
            impact = client.get_ci_impact(a.id, depth=5)
            # Root CI should NOT be in its own impact set
            assert a.id not in [ci.id for ci in impact]
        finally:
            client.delete_relationship(r.id)
            client.delete_ci(a.id)


class TestRootExclusion:
    def test_root_not_in_own_impact(self, client: CMDBClient):
        a = client.create_ci(name="root-excl", type="server")
        b = client.create_ci(name="leaf-excl", type="app")
        r = client.create_relationship(a.id, b.id, type="hosts")
        try:
            impact = client.get_ci_impact(a.id, depth=3)
            assert a.id not in [ci.id for ci in impact]
        finally:
            client.delete_relationship(r.id)
            client.delete_ci(a.id)
            client.delete_ci(b.id)


class TestRelationshipTypeFilter:
    def test_filter_narrows_traversal(self, client: CMDBClient):
        """A →(hosts) B, A →(monitors) C: filtering by 'hosts' excludes C."""
        a = client.create_ci(name="filter-root", type="server")
        b = client.create_ci(name="filter-hosted", type="app")
        c = client.create_ci(name="filter-monitored", type="app")
        r1 = client.create_relationship(a.id, b.id, type="hosts")
        r2 = client.create_relationship(a.id, c.id, type="monitors")
        try:
            impact = client.get_ci_impact(
                a.id, depth=1, relationship_types=["hosts"]
            )
            ids = [ci.id for ci in impact]
            assert b.id in ids
            assert c.id not in ids
        finally:
            client.delete_relationship(r1.id)
            client.delete_relationship(r2.id)
            client.delete_ci(a.id)
            client.delete_ci(b.id)
            client.delete_ci(c.id)
