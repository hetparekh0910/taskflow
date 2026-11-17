import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.billing import plans
from apps.billing.models import StripeEvent
from apps.workspaces.models import Role

from .conftest import Tenant


@pytest.fixture
def free():
    t = Tenant("Freebie", plan="free")
    return t


@pytest.mark.django_db
class TestPlanLimits:
    def test_free_plan_limits_projects(self, free):
        o = free.clients[Role.OWNER]
        assert o.post(free.url("projects/"), {"key": "AA", "name": "a"}, format="json").status_code == 201
        assert o.post(free.url("projects/"), {"key": "BB", "name": "b"}, format="json").status_code == 201
        r = o.post(free.url("projects/"), {"key": "CC", "name": "c"}, format="json")
        assert r.status_code == 402 and r.data["code"] == "plan_limit" and r.data["resource"] == "projects" and r.data["limit"] == 2

    def test_free_plan_limits_members_including_pending_invites(self, free):
        # fixture already has 4 members (> free limit of 3), so any new invite is blocked
        r = free.clients[Role.OWNER].post(free.url("invitations/"), {"email": "x@y.com", "role": "member"}, format="json")
        assert r.status_code == 402 and r.data["resource"] == "members"

    def test_storage_limit(self, free, settings):
        free.make_project("AA", "a")
        issue = free.make_issue("x")
        spec = plans.PLANS["free"]
        big = SimpleUploadedFile("big.bin", b"0" * 1024)
        # shrink the limit instead of uploading 100MB
        plans.PLANS["free"] = plans.PlanSpec("free", "Free", 0, 3, 2, 0, False, 7)
        try:
            r = free.clients[Role.MEMBER].post(free.url("attachments/"), {"issue": issue.id, "file": big}, format="multipart")
            assert r.status_code == 402 and r.data["resource"] == "storage"
        finally:
            plans.PLANS["free"] = spec

    def test_upload_rules(self, acme, settings):
        issue = acme.make_issue("x")
        m = acme.clients[Role.MEMBER]
        assert m.post(acme.url("attachments/"), {"issue": issue.id, "file": SimpleUploadedFile("virus.exe", b"MZ")}, format="multipart").status_code == 400
        settings.MAX_UPLOAD_BYTES = 10
        assert m.post(acme.url("attachments/"), {"issue": issue.id, "file": SimpleUploadedFile("a.txt", b"x" * 50)}, format="multipart").status_code == 400
        settings.MAX_UPLOAD_BYTES = 1000
        r = m.post(acme.url("attachments/"), {"issue": issue.id, "file": SimpleUploadedFile("ok.txt", b"hello")}, format="multipart")
        assert r.status_code == 201 and r.data["name"] == "ok.txt" and "file" not in r.data  # no raw media path exposed

    def test_business_plan_is_unlimited_for_members_and_projects(self, acme):
        o = acme.clients[Role.OWNER]
        for n in range(12):
            assert o.post(acme.url("projects/"), {"key": f"P{n}X", "name": f"p{n}"}, format="json").status_code == 201


@pytest.mark.django_db
class TestMockCheckout:
    def test_upgrade_flow_unlocks_limits_then_cancel_downgrades(self, free):
        o = free.clients[Role.OWNER]
        b = o.get(free.url("billing/")).data
        assert b["plan"] == "free" and b["mode"] == "mock" and b["usage"]["members"] == 4 and b["can_manage"]
        r = o.post(free.url("billing/checkout/"), {"plan": "pro"}, format="json")
        assert r.status_code == 200 and r.data["mock"] and "mock-checkout" in r.data["url"]
        assert o.post(free.url("billing/mock/confirm/"), {"plan": "pro"}, format="json").status_code == 200
        free.ws.refresh_from_db()
        assert free.ws.plan == "pro" and free.ws.subscription_status == "active"
        assert o.post(free.url("billing/checkout/"), {"plan": "pro"}, format="json").status_code == 400  # already on it
        assert o.post(free.url("invitations/"), {"email": "x@y.com", "role": "member"}, format="json").status_code == 201
        assert o.post(free.url("billing/cancel/")).data["plan"] == "free"

    def test_bad_plan_rejected_and_mock_disabled_with_real_keys(self, free, settings):
        o = free.clients[Role.OWNER]
        assert o.post(free.url("billing/checkout/"), {"plan": "enterprise"}, format="json").status_code == 400
        settings.STRIPE_SECRET_KEY = "sk_test_123"
        assert o.post(free.url("billing/mock/confirm/"), {"plan": "pro"}, format="json").status_code == 403


@pytest.mark.django_db
class TestStripeWebhook:
    def _post(self, client, event):
        return client.post("/api/billing/stripe-webhook/", json.dumps(event), content_type="application/json")

    def test_checkout_completed_upgrades_and_is_idempotent(self, free, settings, client):
        settings.DEBUG = True
        ev = {"id": "evt_1", "type": "checkout.session.completed", "data": {"object": {
            "customer": "cus_1", "subscription": "sub_1", "client_reference_id": str(free.ws.id),
            "metadata": {"workspace_id": str(free.ws.id), "plan": "pro"}}}}
        assert self._post(client, ev).json()["status"] == "ok"
        free.ws.refresh_from_db()
        assert free.ws.plan == "pro" and free.ws.stripe_customer_id == "cus_1" and free.ws.stripe_subscription_id == "sub_1"
        free.ws.plan = "free"; free.ws.save()
        assert self._post(client, ev).json()["status"] == "duplicate"  # replay does nothing
        free.ws.refresh_from_db()
        assert free.ws.plan == "free" and StripeEvent.objects.filter(event_id="evt_1").count() == 1

    def test_subscription_deleted_downgrades_and_payment_failed_flags(self, acme, client, settings):
        settings.DEBUG = True
        acme.ws.stripe_customer_id = "cus_9"; acme.ws.save()
        self._post(client, {"id": "e2", "type": "invoice.payment_failed", "data": {"object": {"customer": "cus_9"}}})
        acme.ws.refresh_from_db()
        assert acme.ws.subscription_status == "past_due" and acme.ws.plan == "business"
        self._post(client, {"id": "e3", "type": "customer.subscription.deleted",
                            "data": {"object": {"id": "sub", "status": "canceled", "customer": "cus_9", "items": {"data": []}}}})
        acme.ws.refresh_from_db()
        assert acme.ws.plan == "free"

    def test_unsigned_events_rejected_in_production_and_bad_signature_rejected(self, free, settings, client):
        settings.DEBUG = False
        assert self._post(client, {"id": "e", "type": "x", "data": {"object": {}}}).status_code == 400
        settings.STRIPE_WEBHOOK_SECRET = "whsec_test"
        r = client.post("/api/billing/stripe-webhook/", "{}", content_type="application/json", HTTP_STRIPE_SIGNATURE="t=1,v1=bad")
        assert r.status_code == 400

    def test_unknown_workspace_event_is_ignored_safely(self, client, settings):
        settings.DEBUG = True
        r = self._post(client, {"id": "e5", "type": "customer.subscription.updated", "data": {"object": {"customer": "nobody"}}})
        assert r.status_code == 200 and r.json()["status"] == "no-workspace"
