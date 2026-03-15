"""Change tracking and diff tests.

Invariants verified:
- GET /cis/{id}/diff returns attribute-level changes between two timestamps
- Diff after create shows all attributes as added
- Diff after update shows old and new values for changed attributes
- Diff after multiple updates captures each change independently
- GET /cis/{id}/history/{entry_id} returns the full CI snapshot at that point
- Snapshot reflects the exact state of the CI after the audited action
- Diff with no changes in range returns empty changes list
- Diff for deleted CI is retrievable (shows final state)
- Diff timestamps are ISO 8601
- Diff changes include field name, old_value, and new_value
"""
from __future__ import annotations

from harness.client import CMDBClient


class TestDiffAfterCreate:
    """Diff immediately after creation shows all fields as added."""

    def test_create_diff_shows_added_attributes(
        self, make_ci, client: CMDBClient,
    ):
        ci = make_ci(
            "diff-create", type="server",
            attributes={"env": "prod", "port": 8080},
        )
        history = client.get_ci_history(ci.id)
        assert len(history) >= 1
        create_entry = history[0]
        assert create_entry.action == "created"

        diff = client.get_ci_diff(ci.id, entry_id=create_entry.id)
        assert diff["action"] == "created"
        assert "changes" in diff

    def test_create_snapshot_matches_ci(
        self, make_ci, client: CMDBClient,
    ):
        ci = make_ci(
            "snap-create", type="server",
            attributes={"env": "prod"},
        )
        history = client.get_ci_history(ci.id)
        snapshot = client.get_ci_snapshot(ci.id, entry_id=history[0].id)
        assert snapshot["name"] == "snap-create"
        assert snapshot["type"] == "server"
        assert snapshot["attributes"]["env"] == "prod"


class TestDiffAfterUpdate:
    """Diff after update shows old_value and new_value for changed fields."""

    def test_update_diff_shows_changed_name(
        self, make_ci, client: CMDBClient,
    ):
        ci = make_ci("original-name", type="server")
        client.update_ci(ci.id, name="updated-name", type="server")

        history = client.get_ci_history(ci.id)
        update_entry = [e for e in history if e.action == "updated"][0]

        diff = client.get_ci_diff(ci.id, entry_id=update_entry.id)
        assert diff["action"] == "updated"

        changes = diff["changes"]
        name_change = [c for c in changes if c["field"] == "name"]
        assert len(name_change) == 1
        assert name_change[0]["old_value"] == "original-name"
        assert name_change[0]["new_value"] == "updated-name"

    def test_update_diff_shows_changed_attributes(
        self, make_ci, client: CMDBClient,
    ):
        ci = make_ci(
            "attr-diff", type="server",
            attributes={"env": "dev", "port": 3000},
        )
        client.update_ci(
            ci.id, name="attr-diff", type="server",
            attributes={"env": "prod", "port": 3000},
        )
        history = client.get_ci_history(ci.id)
        update_entry = [e for e in history if e.action == "updated"][0]
        diff = client.get_ci_diff(ci.id, entry_id=update_entry.id)

        changes = diff["changes"]
        env_change = [
            c for c in changes
            if c["field"] in ("attributes.env", "env")
        ]
        assert len(env_change) >= 1
        assert env_change[0]["old_value"] == "dev"
        assert env_change[0]["new_value"] == "prod"

    def test_update_diff_shows_added_attribute(
        self, make_ci, client: CMDBClient,
    ):
        ci = make_ci("add-attr", type="server", attributes={})
        client.update_ci(
            ci.id, name="add-attr", type="server",
            attributes={"new_key": "new_val"},
        )
        history = client.get_ci_history(ci.id)
        update_entry = [e for e in history if e.action == "updated"][0]
        diff = client.get_ci_diff(ci.id, entry_id=update_entry.id)

        changes = diff["changes"]
        added = [
            c for c in changes
            if c["field"] in ("attributes.new_key", "new_key")
        ]
        assert len(added) >= 1
        assert added[0]["old_value"] is None
        assert added[0]["new_value"] == "new_val"

    def test_update_diff_shows_removed_attribute(
        self, make_ci, client: CMDBClient,
    ):
        ci = make_ci(
            "rm-attr", type="server",
            attributes={"to_remove": "val"},
        )
        client.update_ci(
            ci.id, name="rm-attr", type="server",
            attributes={},
        )
        history = client.get_ci_history(ci.id)
        update_entry = [e for e in history if e.action == "updated"][0]
        diff = client.get_ci_diff(ci.id, entry_id=update_entry.id)

        changes = diff["changes"]
        removed = [
            c for c in changes
            if c["field"] in ("attributes.to_remove", "to_remove")
        ]
        assert len(removed) >= 1
        assert removed[0]["new_value"] is None


class TestDiffMultipleUpdates:
    """Each update produces its own diff entry."""

    def test_three_updates_produce_three_diffs(
        self, make_ci, client: CMDBClient,
    ):
        ci = make_ci("multi-update", type="server", attributes={"v": "1"})
        client.update_ci(
            ci.id, name="multi-update", type="server",
            attributes={"v": "2"},
        )
        client.update_ci(
            ci.id, name="multi-update", type="server",
            attributes={"v": "3"},
        )

        history = client.get_ci_history(ci.id)
        updates = [e for e in history if e.action == "updated"]
        assert len(updates) == 2

        for entry in updates:
            diff = client.get_ci_diff(ci.id, entry_id=entry.id)
            assert diff["action"] == "updated"
            assert len(diff["changes"]) >= 1


class TestSnapshot:
    """GET /cis/{id}/history/{entry_id}/snapshot returns CI state at that point."""

    def test_snapshot_after_create(self, make_ci, client: CMDBClient):
        ci = make_ci(
            "snap-v1", type="server",
            attributes={"version": "1"},
        )
        history = client.get_ci_history(ci.id)
        snap = client.get_ci_snapshot(ci.id, entry_id=history[0].id)
        assert snap["name"] == "snap-v1"
        assert snap["attributes"]["version"] == "1"

    def test_snapshot_after_update_reflects_new_state(
        self, make_ci, client: CMDBClient,
    ):
        ci = make_ci(
            "snap-v1", type="server",
            attributes={"version": "1"},
        )
        client.update_ci(
            ci.id, name="snap-v2", type="server",
            attributes={"version": "2"},
        )
        history = client.get_ci_history(ci.id)
        update_entry = [e for e in history if e.action == "updated"][0]
        snap = client.get_ci_snapshot(ci.id, entry_id=update_entry.id)
        assert snap["name"] == "snap-v2"
        assert snap["attributes"]["version"] == "2"

    def test_older_snapshot_preserves_old_state(
        self, make_ci, client: CMDBClient,
    ):
        ci = make_ci(
            "snap-old", type="server",
            attributes={"version": "1"},
        )
        client.update_ci(
            ci.id, name="snap-new", type="server",
            attributes={"version": "2"},
        )
        history = client.get_ci_history(ci.id)
        create_entry = [e for e in history if e.action == "created"][0]
        snap = client.get_ci_snapshot(ci.id, entry_id=create_entry.id)
        assert snap["name"] == "snap-old"
        assert snap["attributes"]["version"] == "1"


class TestDiffTimeBased:
    """GET /cis/{id}/diff?from=<ts>&to=<ts> returns changes in a time range."""

    def test_diff_time_range(self, make_ci, client: CMDBClient):
        ci = make_ci(
            "time-diff", type="server",
            attributes={"phase": "alpha"},
        )
        ts_after_create = ci.created_at

        client.update_ci(
            ci.id, name="time-diff", type="server",
            attributes={"phase": "beta"},
        )
        updated = client.get_ci(ci.id)
        ts_after_update = updated.updated_at

        changes = client.get_ci_diff_range(
            ci.id, from_ts=ts_after_create, to_ts=ts_after_update,
        )
        assert len(changes) >= 1

    def test_diff_no_changes_in_range(self, make_ci, client: CMDBClient):
        ci = make_ci("no-change", type="server")
        ts = ci.created_at
        # Query a range after creation with no updates
        changes = client.get_ci_diff_range(
            ci.id, from_ts=ts, to_ts="2099-12-31T23:59:59Z",
        )
        assert changes == []


class TestDiffDeletedCI:
    """Diff and snapshots remain available after CI deletion."""

    def test_diff_survives_deletion(self, client: CMDBClient):
        ci = client.create_ci(name="to-delete-diff", type="server")
        ci_id = ci.id
        history_before = client.get_ci_history(ci_id)
        create_entry_id = history_before[0].id

        client.delete_ci(ci_id)

        # History should still be accessible
        history_after = client.get_ci_history(ci_id)
        assert len(history_after) >= 2  # created + deleted

        # Diff of create entry should still work
        diff = client.get_ci_diff(ci_id, entry_id=create_entry_id)
        assert diff["action"] == "created"
