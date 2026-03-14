"""Impact analysis scenario tests.

These tests model realistic infrastructure topologies and verify
that the CMDB produces correct impact assessments. They complement
the structural tests in test_traversal.py with domain-specific scenarios.

Scenario: Three-tier web application
  load_balancer → web_server_1 → app_server → database
                → web_server_2 → app_server (shared dependency)

Impact of database failure:  all four upstream CIs are affected.
Impact of web_server_1 failure: only load_balancer is affected upstream.
"""
from __future__ import annotations

import pytest
from harness.client import CMDBClient


@pytest.fixture
def three_tier_topology(client: CMDBClient):
    """Build a realistic three-tier application topology.

    Returns dict of {role: CI} for assertions.
    Cleans up all CIs and relationships after the test.
    """
    db = client.create_ci(name="prod-db", type="database", attributes={"engine": "postgres"})
    app = client.create_ci(name="prod-app", type="app", attributes={"runtime": "python"})
    web1 = client.create_ci(name="prod-web-1", type="server")
    web2 = client.create_ci(name="prod-web-2", type="server")
    lb = client.create_ci(name="prod-lb", type="load_balancer")

    # app → db (depends_on)
    r1 = client.create_relationship(app.id, db.id, type="depends_on")
    # web1, web2 → app (depends_on)
    r2 = client.create_relationship(web1.id, app.id, type="depends_on")
    r3 = client.create_relationship(web2.id, app.id, type="depends_on")
    # lb → web1, web2 (load_balances)
    r4 = client.create_relationship(lb.id, web1.id, type="load_balances")
    r5 = client.create_relationship(lb.id, web2.id, type="load_balances")

    topo = {
        "db": db, "app": app, "web1": web1, "web2": web2, "lb": lb,
        "_rels": [r1, r2, r3, r4, r5],
    }

    yield topo

    # Teardown
    for rel in topo["_rels"]:
        try:
            client.delete_relationship(rel.id)
        except Exception:
            pass
    for role in ["lb", "web1", "web2", "app", "db"]:
        try:
            client.delete_ci(topo[role].id)
        except Exception:
            pass


class TestThreeTierImpact:
    def test_database_failure_impacts_all_upstream(
        self, client: CMDBClient, three_tier_topology
    ):
        """If the database goes down, everything upstream is affected."""
        t = three_tier_topology
        # dependencies of db = CIs that depend (transitively) on db
        deps = client.get_ci_dependencies(t["db"].id, depth=10)
        dep_ids = {ci.id for ci in deps}
        assert t["app"].id in dep_ids, "App depends on DB"
        assert t["web1"].id in dep_ids, "Web1 transitively depends on DB"
        assert t["web2"].id in dep_ids, "Web2 transitively depends on DB"
        assert t["lb"].id in dep_ids, "LB transitively depends on DB"

    def test_web_server_failure_limited_impact(
        self, client: CMDBClient, three_tier_topology
    ):
        """If one web server fails, only the LB is directly affected."""
        t = three_tier_topology
        deps = client.get_ci_dependencies(t["web1"].id, depth=1)
        dep_ids = {ci.id for ci in deps}
        assert t["lb"].id in dep_ids, "LB depends on web1"
        assert t["web2"].id not in dep_ids, "web2 is not affected by web1"

    def test_lb_has_no_downstream_impact(
        self, client: CMDBClient, three_tier_topology
    ):
        """The load balancer is the edge — nothing depends on it."""
        t = three_tier_topology
        deps = client.get_ci_dependencies(t["lb"].id, depth=1)
        assert len(deps) == 0, "Nothing should depend on the LB"

    def test_app_impact_reaches_database(
        self, client: CMDBClient, three_tier_topology
    ):
        """App's downstream impact includes the database."""
        t = three_tier_topology
        impact = client.get_ci_impact(t["app"].id, depth=1)
        impact_ids = {ci.id for ci in impact}
        assert t["db"].id in impact_ids, "DB is a direct downstream of app"

    def test_full_depth_traversal_finds_all(
        self, client: CMDBClient, three_tier_topology
    ):
        """From the LB, full-depth impact should reach the database."""
        t = three_tier_topology
        impact = client.get_ci_impact(t["lb"].id, depth=10)
        impact_ids = {ci.id for ci in impact}
        assert t["web1"].id in impact_ids
        assert t["web2"].id in impact_ids
        assert t["app"].id in impact_ids
        assert t["db"].id in impact_ids
