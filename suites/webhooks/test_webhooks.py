"""Webhook subscription and delivery tests.

Invariants verified:
- POST /webhooks registers a webhook subscription
- GET /webhooks lists all subscriptions
- GET /webhooks/{id} returns a single subscription
- DELETE /webhooks/{id} removes a subscription
- POST /webhooks/{id}/test triggers a test ping delivery
- GET /webhooks/{id}/deliveries returns delivery history
- Webhooks can filter by event type (ci.created, ci.updated, ci.deleted)
- Test ping creates a delivery record
- Missing or invalid fields are rejected with 422
- Operations on nonexistent webhooks return 404
"""
from __future__ import annotations

from harness.client import CMDBClient


class TestWebhookCRUD:
    """POST/GET/DELETE /webhooks manage webhook subscriptions."""

    def test_create_webhook(self, make_webhook, client: CMDBClient):
        wh = make_webhook(
            url="https://example.com/hook",
            events=["ci.created", "ci.updated"],
        )
        assert wh.id
        assert wh.url == "https://example.com/hook"
        assert "ci.created" in wh.events
        assert wh.active is True

    def test_get_webhook(self, make_webhook, client: CMDBClient):
        wh = make_webhook()
        fetched = client.get_webhook(wh.id)
        assert fetched.id == wh.id
        assert fetched.url == wh.url

    def test_list_webhooks(self, make_webhook, client: CMDBClient):
        wh1 = make_webhook(url="https://example.com/hook1")
        wh2 = make_webhook(url="https://example.com/hook2")
        all_wh = client.list_webhooks()
        ids = [w.id for w in all_wh]
        assert wh1.id in ids
        assert wh2.id in ids

    def test_delete_webhook(self, client: CMDBClient):
        wh = client.create_webhook(
            url="https://example.com/delete-me",
            events=["ci.created"],
        )
        client.delete_webhook(wh.id)
        resp = client.raw_get(f"/webhooks/{wh.id}")
        assert resp.status_code == 404

    def test_delete_nonexistent_404(self, client: CMDBClient):
        resp = client.raw_request("DELETE", "/webhooks/nonexistent-id")
        assert resp.status_code == 404

    def test_get_nonexistent_404(self, client: CMDBClient):
        resp = client.raw_get("/webhooks/nonexistent-id")
        assert resp.status_code == 404


class TestWebhookEventFiltering:
    """Webhooks subscribe to specific event types."""

    def test_subscribe_to_specific_events(self, make_webhook, client: CMDBClient):
        wh = make_webhook(events=["ci.created"])
        assert wh.events == ["ci.created"]

    def test_subscribe_to_multiple_events(self, make_webhook, client: CMDBClient):
        wh = make_webhook(events=["ci.created", "ci.updated", "ci.deleted"])
        assert sorted(wh.events) == ["ci.created", "ci.deleted", "ci.updated"]


class TestWebhookDelivery:
    """POST /webhooks/{id}/test and GET /webhooks/{id}/deliveries."""

    def test_ping_creates_delivery(self, make_webhook, client: CMDBClient):
        wh = make_webhook()
        client.test_webhook(wh.id)
        deliveries = client.get_webhook_deliveries(wh.id)
        assert len(deliveries) >= 1

    def test_delivery_records_event_type(self, make_webhook, client: CMDBClient):
        wh = make_webhook()
        client.test_webhook(wh.id)
        deliveries = client.get_webhook_deliveries(wh.id)
        assert any(d.event == "ping" for d in deliveries)

    def test_deliveries_empty_before_test(self, make_webhook, client: CMDBClient):
        wh = make_webhook()
        deliveries = client.get_webhook_deliveries(wh.id)
        assert len(deliveries) == 0

    def test_deliveries_for_nonexistent_webhook_404(self, client: CMDBClient):
        resp = client.raw_get("/webhooks/nonexistent/deliveries")
        assert resp.status_code == 404

    def test_test_nonexistent_webhook_404(self, client: CMDBClient):
        resp = client.raw_request("POST", "/webhooks/nonexistent/test")
        assert resp.status_code == 404


class TestWebhookValidation:
    """Webhook inputs are validated."""

    def test_missing_url_rejected(self, client: CMDBClient):
        resp = client.raw_post("/webhooks", {
            "events": ["ci.created"],
        })
        assert resp.status_code in (400, 422)

    def test_missing_events_rejected(self, client: CMDBClient):
        resp = client.raw_post("/webhooks", {
            "url": "https://example.com/hook",
        })
        assert resp.status_code in (400, 422)

    def test_empty_events_rejected(self, client: CMDBClient):
        resp = client.raw_post("/webhooks", {
            "url": "https://example.com/hook",
            "events": [],
        })
        assert resp.status_code in (400, 422)

    def test_invalid_url_rejected(self, client: CMDBClient):
        resp = client.raw_post("/webhooks", {
            "url": "not-a-url",
            "events": ["ci.created"],
        })
        assert resp.status_code in (400, 422)
