"""Reconciliation tests.

Invariants verified:
- POST /cis/reconcile accepts a source name and a list of CIs from that source
- Response classifies each CI as: new, updated, unchanged, or stale
- New CIs (in source but not CMDB) are identified correctly
- Updated CIs (in both, but source has different attributes) are identified
- Unchanged CIs (in both, identical) are identified
- Stale CIs (in CMDB with this source but not in the new source list) are flagged
- Reconcile with apply=true creates new CIs and updates changed ones
- Reconcile with apply=false is a dry run — no mutations
- Source field is preserved on created/updated CIs
- Stale CIs are not auto-deleted, only flagged
- Reconcile is idempotent: running twice with same data = all unchanged
- Empty source list flags all existing CIs from that source as stale
"""
from __future__ import annotations

from harness.client import CMDBClient


class TestReconcileDryRun:
    """POST /cis/reconcile with apply=false previews changes."""

    def test_new_cis_detected(self, client: CMDBClient):
        result = client.reconcile(
            source="test-source-new",
            items=[
                {"name": "recon-new-1", "type": "server"},
                {"name": "recon-new-2", "type": "database"},
            ],
            apply=False,
        )
        assert len(result["new"]) == 2
        assert len(result["updated"]) == 0
        assert len(result["unchanged"]) == 0

    def test_dry_run_does_not_create(self, client: CMDBClient):
        client.reconcile(
            source="test-dry-run",
            items=[{"name": "should-not-exist", "type": "server"}],
            apply=False,
        )
        results = client.search_cis(q="should-not-exist")
        assert len(results) == 0

    def test_unchanged_detected(self, make_ci, client: CMDBClient):
        # Create a CI with a source (assignment needed to keep fixture cleanup)
        make_ci(
            "recon-existing", type="server",
            attributes={"source": "src-unchanged", "env": "prod"},
        )
        result = client.reconcile(
            source="src-unchanged",
            items=[{
                "name": "recon-existing",
                "type": "server",
                "attributes": {"env": "prod"},
            }],
            apply=False,
        )
        assert len(result["unchanged"]) >= 1
        unchanged_names = [i["name"] for i in result["unchanged"]]
        assert "recon-existing" in unchanged_names

    def test_updated_detected(self, make_ci, client: CMDBClient):
        make_ci(
            "recon-update-me", type="server",
            attributes={"source": "src-update", "env": "dev"},
        )
        result = client.reconcile(
            source="src-update",
            items=[{
                "name": "recon-update-me",
                "type": "server",
                "attributes": {"env": "prod"},  # changed
            }],
            apply=False,
        )
        assert len(result["updated"]) >= 1
        updated_names = [i["name"] for i in result["updated"]]
        assert "recon-update-me" in updated_names

    def test_stale_detected(self, make_ci, client: CMDBClient):
        make_ci(
            "recon-stale-ci", type="server",
            attributes={"source": "src-stale"},
        )
        # Reconcile with empty list — existing CI becomes stale
        result = client.reconcile(
            source="src-stale",
            items=[],
            apply=False,
        )
        assert len(result["stale"]) >= 1
        stale_names = [i["name"] for i in result["stale"]]
        assert "recon-stale-ci" in stale_names


class TestReconcileApply:
    """POST /cis/reconcile with apply=true mutates the CMDB."""

    def test_apply_creates_new_cis(self, client: CMDBClient):
        result = client.reconcile(
            source="src-apply-new",
            items=[
                {"name": "applied-new-1", "type": "server"},
                {"name": "applied-new-2", "type": "database"},
            ],
            apply=True,
        )
        assert len(result["new"]) == 2

        # Verify they now exist
        for item in result["new"]:
            ci = client.get_ci(item["id"])
            assert ci.attributes.get("source") == "src-apply-new"

        # Cleanup
        for item in result["new"]:
            try:
                client.delete_ci(item["id"])
            except Exception:
                pass

    def test_apply_updates_changed_cis(self, make_ci, client: CMDBClient):
        ci = make_ci(
            "apply-update-me", type="server",
            attributes={"source": "src-apply-upd", "version": "1"},
        )
        result = client.reconcile(
            source="src-apply-upd",
            items=[{
                "name": "apply-update-me",
                "type": "server",
                "attributes": {"version": "2"},
            }],
            apply=True,
        )
        assert len(result["updated"]) >= 1

        # Verify the update
        refreshed = client.get_ci(ci.id)
        assert refreshed.attributes.get("version") == "2"

    def test_apply_does_not_delete_stale(
        self, make_ci, client: CMDBClient,
    ):
        ci = make_ci(
            "apply-stale-keep", type="server",
            attributes={"source": "src-apply-stale"},
        )
        result = client.reconcile(
            source="src-apply-stale",
            items=[],
            apply=True,
        )
        assert len(result["stale"]) >= 1

        # Stale CI should still exist
        fetched = client.get_ci(ci.id)
        assert fetched.name == "apply-stale-keep"

    def test_apply_preserves_source(self, client: CMDBClient):
        result = client.reconcile(
            source="src-tagged",
            items=[{"name": "source-tagged", "type": "server"}],
            apply=True,
        )
        ci_id = result["new"][0]["id"]
        try:
            ci = client.get_ci(ci_id)
            assert ci.attributes.get("source") == "src-tagged"
        finally:
            try:
                client.delete_ci(ci_id)
            except Exception:
                pass


class TestReconcileIdempotency:
    """Running reconcile twice with the same data = all unchanged."""

    def test_second_run_all_unchanged(self, client: CMDBClient):
        items = [
            {"name": "idemp-1", "type": "server", "attributes": {"v": "1"}},
            {"name": "idemp-2", "type": "database", "attributes": {"v": "1"}},
        ]

        # First run: creates new
        r1 = client.reconcile(source="src-idemp", items=items, apply=True)
        assert len(r1["new"]) == 2

        try:
            # Second run: all unchanged
            r2 = client.reconcile(
                source="src-idemp", items=items, apply=True,
            )
            assert len(r2["unchanged"]) == 2
            assert len(r2["new"]) == 0
            assert len(r2["updated"]) == 0
        finally:
            for item in r1["new"]:
                try:
                    client.delete_ci(item["id"])
                except Exception:
                    pass


class TestReconcileSourceIsolation:
    """Reconcile only considers CIs from the specified source."""

    def test_different_source_not_flagged_stale(
        self, make_ci, client: CMDBClient,
    ):
        make_ci(
            "other-source-ci", type="server",
            attributes={"source": "source-A"},
        )
        result = client.reconcile(
            source="source-B",
            items=[],
            apply=False,
        )
        stale_names = [i["name"] for i in result["stale"]]
        assert "other-source-ci" not in stale_names

    def test_source_matching_is_exact(self, make_ci, client: CMDBClient):
        make_ci(
            "exact-match-ci", type="server",
            attributes={"source": "aws-prod"},
        )
        result = client.reconcile(
            source="aws",  # prefix, not exact
            items=[],
            apply=False,
        )
        stale_names = [i["name"] for i in result["stale"]]
        assert "exact-match-ci" not in stale_names


class TestReconcileValidation:
    """Reconcile rejects invalid input."""

    def test_missing_source_rejected(self, client: CMDBClient):
        resp = client.raw_post("/cis/reconcile", {
            "items": [{"name": "x", "type": "server"}],
        })
        assert resp.status_code in (400, 422)

    def test_missing_items_rejected(self, client: CMDBClient):
        resp = client.raw_post("/cis/reconcile", {
            "source": "test",
        })
        assert resp.status_code in (400, 422)

    def test_item_missing_name_rejected(self, client: CMDBClient):
        resp = client.raw_post("/cis/reconcile", {
            "source": "test",
            "items": [{"type": "server"}],
            "apply": False,
        })
        assert resp.status_code in (400, 422)
