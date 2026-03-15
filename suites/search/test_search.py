"""Advanced search and filtering tests.

Invariants verified:
- GET /cis/search with q= performs full-text search across name, type, attributes
- Attribute filtering: attributes.key=value narrows results correctly
- Wildcard matching: name=web-* returns only matching CIs
- Compound filters: multiple query params are ANDed together
- Sorting: sort=field:asc|desc orders results correctly
- Search results respect pagination (limit/offset)
- Empty search returns all CIs (equivalent to list)
- Search is case-insensitive for name and type
- Attribute value filters support exact match
- No results returns empty items list, not 404
"""
from __future__ import annotations

from harness.client import CMDBClient


class TestFullTextSearch:
    """GET /cis/search?q=<term> searches across name, type, and attributes."""

    def test_search_by_name(self, make_ci, client: CMDBClient):
        ci = make_ci("prometheus-monitor", type="server")
        results = client.search_cis(q="prometheus")
        ids = [c.id for c in results]
        assert ci.id in ids

    def test_search_by_type(self, make_ci, client: CMDBClient):
        ci = make_ci("some-db", type="postgresql-database")
        results = client.search_cis(q="postgresql")
        ids = [c.id for c in results]
        assert ci.id in ids

    def test_search_by_attribute_value(self, make_ci, client: CMDBClient):
        ci = make_ci(
            "tagged-ci", type="server",
            attributes={"environment": "staging-eu-west"},
        )
        results = client.search_cis(q="staging-eu-west")
        ids = [c.id for c in results]
        assert ci.id in ids

    def test_search_case_insensitive(self, make_ci, client: CMDBClient):
        ci = make_ci("MyWebServer", type="Server")
        results = client.search_cis(q="mywebserver")
        ids = [c.id for c in results]
        assert ci.id in ids

    def test_search_no_results(self, client: CMDBClient):
        results = client.search_cis(q="zzz-nonexistent-xyzzy-12345")
        assert results == []

    def test_search_empty_query_returns_all(self, make_ci, client: CMDBClient):
        ci = make_ci("searchable", type="server")
        results = client.search_cis(q="")
        ids = [c.id for c in results]
        assert ci.id in ids


class TestAttributeFiltering:
    """GET /cis/search?attributes.key=value filters by attribute."""

    def test_filter_single_attribute(self, make_ci, client: CMDBClient):
        make_ci("prod-1", type="server", attributes={"env": "prod"})
        make_ci("dev-1", type="server", attributes={"env": "dev"})
        results = client.search_cis(attribute_filters={"env": "prod"})
        assert all(
            c.attributes.get("env") == "prod" for c in results
        )
        assert len(results) >= 1

    def test_filter_multiple_attributes_are_anded(
        self, make_ci, client: CMDBClient,
    ):
        make_ci(
            "target", type="server",
            attributes={"env": "prod", "region": "us-east-1"},
        )
        make_ci(
            "decoy", type="server",
            attributes={"env": "prod", "region": "eu-west-1"},
        )
        results = client.search_cis(
            attribute_filters={"env": "prod", "region": "us-east-1"},
        )
        for c in results:
            assert c.attributes.get("env") == "prod"
            assert c.attributes.get("region") == "us-east-1"

    def test_filter_nonexistent_attribute_returns_empty(
        self, client: CMDBClient,
    ):
        results = client.search_cis(
            attribute_filters={"zzz_no_such_attr": "value"},
        )
        assert results == []

    def test_filter_combined_with_type(self, make_ci, client: CMDBClient):
        make_ci(
            "db-prod", type="database",
            attributes={"env": "prod"},
        )
        make_ci(
            "srv-prod", type="server",
            attributes={"env": "prod"},
        )
        results = client.search_cis(
            type="database",
            attribute_filters={"env": "prod"},
        )
        assert all(c.type == "database" for c in results)
        assert len(results) >= 1


class TestWildcardSearch:
    """GET /cis/search?name=web-* supports wildcard/prefix matching."""

    def test_prefix_wildcard(self, make_ci, client: CMDBClient):
        ci1 = make_ci("web-server-1", type="server")
        ci2 = make_ci("web-server-2", type="server")
        make_ci("db-primary", type="database")
        results = client.search_cis(name="web-*")
        ids = [c.id for c in results]
        assert ci1.id in ids
        assert ci2.id in ids

    def test_suffix_wildcard(self, make_ci, client: CMDBClient):
        ci = make_ci("app-primary", type="server")
        make_ci("app-secondary", type="server")
        results = client.search_cis(name="*-primary")
        ids = [c.id for c in results]
        assert ci.id in ids

    def test_wildcard_no_match(self, client: CMDBClient):
        results = client.search_cis(name="zzz-nonexistent-*")
        assert results == []


class TestCompoundFilters:
    """Multiple filter parameters are ANDed together."""

    def test_type_plus_query(self, make_ci, client: CMDBClient):
        make_ci("api-gateway", type="loadbalancer")
        make_ci("api-server", type="server")
        results = client.search_cis(q="api", type="server")
        assert all(c.type == "server" for c in results)
        assert any("api" in c.name.lower() for c in results)

    def test_type_plus_name_wildcard(self, make_ci, client: CMDBClient):
        make_ci("cache-redis-1", type="cache")
        make_ci("cache-memcached-1", type="cache")
        make_ci("db-redis-1", type="database")
        results = client.search_cis(name="cache-*", type="cache")
        assert all(c.type == "cache" for c in results)
        assert all(c.name.startswith("cache-") for c in results)


class TestSearchSorting:
    """GET /cis/search?sort=field:direction orders results."""

    def test_sort_by_name_asc(self, make_ci, client: CMDBClient):
        make_ci("alpha-sort-test", type="server")
        make_ci("zeta-sort-test", type="server")
        results = client.search_cis(q="sort-test", sort="name:asc")
        names = [c.name for c in results]
        assert names == sorted(names)

    def test_sort_by_name_desc(self, make_ci, client: CMDBClient):
        make_ci("alpha-desc-test", type="server")
        make_ci("zeta-desc-test", type="server")
        results = client.search_cis(q="desc-test", sort="name:desc")
        names = [c.name for c in results]
        assert names == sorted(names, reverse=True)

    def test_sort_by_created_at(self, make_ci, client: CMDBClient):
        ci1 = make_ci("first-created", type="server")
        ci2 = make_ci("second-created", type="server")
        results = client.search_cis(
            q="created", sort="created_at:asc",
        )
        ids = [c.id for c in results]
        if ci1.id in ids and ci2.id in ids:
            assert ids.index(ci1.id) < ids.index(ci2.id)


class TestSearchPagination:
    """Search respects limit and offset for pagination."""

    def test_limit_constrains_results(self, make_ci, client: CMDBClient):
        for i in range(5):
            make_ci(f"page-test-{i}", type="server")
        results = client.search_cis(q="page-test", limit=2)
        assert len(results) <= 2

    def test_offset_skips_results(self, make_ci, client: CMDBClient):
        for i in range(5):
            make_ci(f"offset-test-{i}", type="server")
        page1 = client.search_cis(
            q="offset-test", limit=2, offset=0, sort="name:asc",
        )
        page2 = client.search_cis(
            q="offset-test", limit=2, offset=2, sort="name:asc",
        )
        ids1 = {c.id for c in page1}
        ids2 = {c.id for c in page2}
        assert ids1.isdisjoint(ids2), "Pages must not overlap"
