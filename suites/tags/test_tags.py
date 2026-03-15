"""Tags and classification tests.

Invariants verified:
- PUT /cis/{id}/tags sets tags on a CI (full replacement)
- GET /cis/{id}/tags returns the current tag list
- DELETE /cis/{id}/tags/{tag} removes a single tag
- Tags are returned as part of GET /cis/{id}
- Duplicate tags are deduplicated
- Setting empty tags clears all tags
- GET /tags lists all known tags with usage counts
- Search supports tag= filter parameter
- Tag operations on nonexistent CIs return 404
- Non-string tags are rejected with 422
"""
from __future__ import annotations

from harness.client import CMDBClient


class TestTagCRUD:
    """PUT /cis/{id}/tags and GET /cis/{id}/tags manage CI tags."""

    def test_set_and_get_tags(self, make_ci, client: CMDBClient):
        ci = make_ci("tagged-server", type="server")
        client.set_ci_tags(ci.id, ["prod", "critical"])
        tags = client.get_ci_tags(ci.id)
        assert sorted(tags) == ["critical", "prod"]

    def test_set_tags_replaces_existing(self, make_ci, client: CMDBClient):
        ci = make_ci("replace-tags", type="server")
        client.set_ci_tags(ci.id, ["v1", "old"])
        client.set_ci_tags(ci.id, ["v2", "new"])
        tags = client.get_ci_tags(ci.id)
        assert sorted(tags) == ["new", "v2"]
        assert "v1" not in tags
        assert "old" not in tags

    def test_set_empty_tags_clears(self, make_ci, client: CMDBClient):
        ci = make_ci("clear-tags", type="server")
        client.set_ci_tags(ci.id, ["prod"])
        client.set_ci_tags(ci.id, [])
        tags = client.get_ci_tags(ci.id)
        assert tags == []

    def test_tags_on_nonexistent_ci_404(self, client: CMDBClient):
        resp = client.raw_get("/cis/nonexistent-id/tags")
        assert resp.status_code == 404

    def test_set_tags_on_nonexistent_ci_404(self, client: CMDBClient):
        resp = client.raw_request(
            "PUT", "/cis/nonexistent-id/tags",
            json={"tags": ["prod"]},
        )
        assert resp.status_code == 404

    def test_tags_returned_in_ci_get(self, make_ci, client: CMDBClient):
        ci = make_ci("ci-with-tags", type="server")
        client.set_ci_tags(ci.id, ["web", "frontend"])
        refreshed = client.get_ci(ci.id)
        assert sorted(refreshed.tags) == ["frontend", "web"]

    def test_duplicate_tags_deduplicated(self, make_ci, client: CMDBClient):
        ci = make_ci("dedup-tags", type="server")
        client.set_ci_tags(ci.id, ["a", "a", "b", "b", "a"])
        tags = client.get_ci_tags(ci.id)
        assert sorted(tags) == ["a", "b"]


class TestTagRemoval:
    """DELETE /cis/{id}/tags/{tag} removes a single tag."""

    def test_remove_single_tag(self, make_ci, client: CMDBClient):
        ci = make_ci("remove-one", type="server")
        client.set_ci_tags(ci.id, ["keep", "remove-me", "also-keep"])
        client.remove_ci_tag(ci.id, "remove-me")
        tags = client.get_ci_tags(ci.id)
        assert sorted(tags) == ["also-keep", "keep"]

    def test_remove_nonexistent_tag_404(self, make_ci, client: CMDBClient):
        ci = make_ci("no-such-tag", type="server")
        client.set_ci_tags(ci.id, ["exists"])
        resp = client.raw_request("DELETE", f"/cis/{ci.id}/tags/not-here")
        assert resp.status_code == 404

    def test_remove_from_nonexistent_ci_404(self, client: CMDBClient):
        resp = client.raw_request("DELETE", "/cis/nonexistent/tags/any")
        assert resp.status_code == 404


class TestTagSearch:
    """GET /cis/search?tag=<value> filters CIs by tag."""

    def test_search_by_tag(self, make_ci, client: CMDBClient):
        ci1 = make_ci("tagged-1", type="server")
        ci2 = make_ci("tagged-2", type="server")
        make_ci("untagged", type="server")
        client.set_ci_tags(ci1.id, ["production"])
        client.set_ci_tags(ci2.id, ["production", "us-east"])
        results = client.search_cis(tag="production")
        ids = [c.id for c in results]
        assert ci1.id in ids
        assert ci2.id in ids

    def test_search_by_tag_no_match(self, client: CMDBClient):
        results = client.search_cis(tag="zzz-no-such-tag")
        assert results == []

    def test_search_tag_combined_with_type(self, make_ci, client: CMDBClient):
        ci_srv = make_ci("tag-srv", type="server")
        ci_db = make_ci("tag-db", type="database")
        client.set_ci_tags(ci_srv.id, ["prod"])
        client.set_ci_tags(ci_db.id, ["prod"])
        results = client.search_cis(tag="prod", type="server")
        assert all(c.type == "server" for c in results)
        assert any(c.id == ci_srv.id for c in results)


class TestTagListing:
    """GET /tags lists all known tags with usage counts."""

    def test_list_all_tags(self, make_ci, client: CMDBClient):
        ci1 = make_ci("list-tags-1", type="server")
        ci2 = make_ci("list-tags-2", type="server")
        client.set_ci_tags(ci1.id, ["infra", "shared-tag"])
        client.set_ci_tags(ci2.id, ["shared-tag"])
        tags = client.list_tags()
        tag_map = {t.tag: t.count for t in tags}
        assert "shared-tag" in tag_map
        assert tag_map["shared-tag"] >= 2

    def test_tag_count_reflects_usage(self, make_ci, client: CMDBClient):
        cis = [make_ci(f"count-tag-{i}", type="server") for i in range(3)]
        for ci in cis:
            client.set_ci_tags(ci.id, ["counted-tag"])
        tags = client.list_tags()
        tag_map = {t.tag: t.count for t in tags}
        assert tag_map.get("counted-tag", 0) >= 3


class TestTagValidation:
    """Tag inputs are validated."""

    def test_non_string_tags_rejected(self, make_ci, client: CMDBClient):
        ci = make_ci("bad-tags", type="server")
        resp = client.raw_request(
            "PUT", f"/cis/{ci.id}/tags",
            json={"tags": [1, True]},
        )
        assert resp.status_code in (400, 422)

    def test_empty_string_tag_rejected(self, make_ci, client: CMDBClient):
        ci = make_ci("empty-tag", type="server")
        resp = client.raw_request(
            "PUT", f"/cis/{ci.id}/tags",
            json={"tags": ["valid", ""]},
        )
        assert resp.status_code in (400, 422)
