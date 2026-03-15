"""Audit trail / CI history tests.

The CMDB must record an immutable history of changes to each CI.
Every create, update, and delete produces an audit entry retrievable
via GET /cis/{id}/history.

Invariants:
- Creating a CI produces a "created" audit entry
- Updating a CI produces an "updated" entry with the changed fields
- Deleting a CI produces a "deleted" entry
- History entries have monotonically increasing timestamps
- History is append-only — entries cannot be modified or deleted
- History for a nonexistent CI returns 404
"""
from __future__ import annotations

import pytest

from harness.client import CMDBClient, NotFoundError


class TestHistoryOnCreate:
    def test_create_produces_audit_entry(self, client: CMDBClient):
        ci = client.create_ci(name="audit-create", type="server")
        try:
            history = client.get_ci_history(ci.id)
            assert len(history) >= 1
            entry = history[0]
            assert entry.ci_id == ci.id
            assert entry.action == "created"
            assert entry.timestamp, "Audit entry must have a timestamp"
        finally:
            client.delete_ci(ci.id)


class TestHistoryOnUpdate:
    def test_update_produces_audit_entry(self, client: CMDBClient):
        ci = client.create_ci(name="audit-update", type="server")
        try:
            client.update_ci(ci.id, name="audit-updated", type="server")
            history = client.get_ci_history(ci.id)
            actions = [e.action for e in history]
            assert "updated" in actions
        finally:
            client.delete_ci(ci.id)

    def test_multiple_updates_produce_multiple_entries(self, client: CMDBClient):
        ci = client.create_ci(name="multi-update", type="server")
        try:
            client.update_ci(ci.id, name="v2", type="server")
            client.update_ci(ci.id, name="v3", type="server")
            history = client.get_ci_history(ci.id)
            update_entries = [e for e in history if e.action == "updated"]
            assert len(update_entries) >= 2
        finally:
            client.delete_ci(ci.id)


class TestHistoryOnDelete:
    def test_delete_produces_audit_entry(self, client: CMDBClient):
        ci = client.create_ci(name="audit-delete", type="server")
        ci_id = ci.id
        client.delete_ci(ci_id)
        # History should still be accessible after deletion
        history = client.get_ci_history(ci_id)
        actions = [e.action for e in history]
        assert "deleted" in actions


class TestHistoryOrdering:
    def test_entries_are_chronological(self, client: CMDBClient):
        ci = client.create_ci(name="ordered-v1", type="server")
        try:
            client.update_ci(ci.id, name="ordered-v2", type="server")
            client.update_ci(ci.id, name="ordered-v3", type="vm")
            history = client.get_ci_history(ci.id)
            timestamps = [e.timestamp for e in history]
            assert timestamps == sorted(timestamps), (
                "History entries must be in chronological order"
            )
        finally:
            client.delete_ci(ci.id)

    def test_action_sequence_matches_operations(self, client: CMDBClient):
        ci = client.create_ci(name="seq-test", type="server")
        client.update_ci(ci.id, name="seq-test-v2", type="server")
        ci_id = ci.id
        client.delete_ci(ci_id)
        history = client.get_ci_history(ci_id)
        actions = [e.action for e in history]
        assert actions == ["created", "updated", "deleted"]


class TestHistoryImmutability:
    def test_history_is_append_only(self, client: CMDBClient):
        """Updating a CI must not alter previous history entries."""
        ci = client.create_ci(
            name="immutable-v1", type="server", attributes={"version": 1}
        )
        try:
            history_before = client.get_ci_history(ci.id)
            first_entry_id = history_before[0].id

            client.update_ci(ci.id, name="immutable-v2", type="server", attributes={"version": 2})
            history_after = client.get_ci_history(ci.id)

            # First entry must be unchanged
            refetched = [e for e in history_after if e.id == first_entry_id][0]
            assert refetched.action == history_before[0].action
            assert refetched.timestamp == history_before[0].timestamp
        finally:
            client.delete_ci(ci.id)


class TestHistoryNotFound:
    def test_history_for_nonexistent_ci(self, client: CMDBClient):
        with pytest.raises(NotFoundError):
            client.get_ci_history("00000000-0000-0000-0000-ffffffffffff")
