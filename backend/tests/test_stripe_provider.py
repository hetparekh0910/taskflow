"""Exercises the real StripeProvider + sync + webhook code against a fake `stripe` library,
so the Stripe integration is tested without a Stripe account or network."""
import json
from types import SimpleNamespace

import pytest

from apps.billing import providers
from apps.billing.providers import StripeProvider
from apps.workspaces.models import Role

from .conftest import Tenant


class FakeStripeError(Exception):
    user_message = "Your card was declined."


class FakeStripe:
    """Records calls and returns canned data shaped like Stripe's responses."""

    StripeError = FakeStripeError

    def __init__(self):
        self.calls = []
        self.subs = []
        self.fail = False
        outer = self

        class Customer:
            @staticmethod
            def create(**kw):
                outer.calls.append(("Customer.create", kw))
                return {"id": "cus_123"}

        class Session:
            @staticmethod
            def create(**kw):
                if outer.fail:
                    raise FakeStripeError()
                outer.calls.append(("Checkout.create", kw))
                return {"url": "https://checkout.stripe.test/c/pay/abc"}

        class PortalSession:
            @staticmethod
            def create(**kw):
                outer.calls.append(("Portal.create", kw))
                return {"url": "https://billing.stripe.test/p/session"}

        class Subscription:
            @staticmethod
            def list(**kw):
                outer.calls.append(("Subscription.list", kw))
                import stripe as real
                return real.convert_to_stripe_object({"object": "list", "data": outer.subs, "has_more": False})

            @staticmethod
            def cancel(sid):
                outer.calls.append(("Subscription.cancel", sid))

        self.Customer = Customer
        self.checkout = SimpleNamespace(Session=Session)
        self.billing_portal = SimpleNamespace(Session=PortalSession)
        self.Subscription = Subscription


def sub(status="active", price="price_pro", sid="sub_1", plan_meta="pro"):
    return {"id": sid, "status": status, "items": {"data": [{"price": {"id": price}}]}, "metadata": {"plan": plan_meta}}


@pytest.fixture
def fake(monkeypatch, settings):
    settings.STRIPE_SECRET_KEY = "sk_test_fake"
    settings.STRIPE_PRICE_PRO = "price_pro"
    settings.STRIPE_PRICE_BUSINESS = "price_biz"
    f = FakeStripe()
    monkeypatch.setattr(StripeProvider, "__init__", lambda self: (setattr(self, "stripe", f), None)[1])
    return f


@pytest.fixture
def free():
    return Tenant("Freebie", plan="free")


@pytest.mark.django_db
class TestStripeCheckout:
    def test_checkout_creates_customer_once_and_session_with_correct_price_and_metadata(self, free, fake):
        o = free.clients[Role.OWNER]
        r = o.post(free.url("billing/checkout/"), {"plan": "business"}, format="json")
        assert r.status_code == 200 and r.data == {"url": "https://checkout.stripe.test/c/pay/abc", "mock": False}
        free.ws.refresh_from_db()
        assert free.ws.stripe_customer_id == "cus_123"
        _, kw = next(c for c in fake.calls if c[0] == "Checkout.create")
        assert kw["mode"] == "subscription" and kw["customer"] == "cus_123"
        assert kw["line_items"] == [{"price": "price_biz", "quantity": 1}]
        assert kw["metadata"] == {"workspace_id": str(free.ws.id), "plan": "business"}
        assert kw["subscription_data"]["metadata"]["workspace_id"] == str(free.ws.id)
        assert kw["success_url"].endswith("?checkout=success") and kw["cancel_url"].endswith("?checkout=cancelled")
        # second checkout reuses the same Stripe customer
        o.post(free.url("billing/checkout/"), {"plan": "pro"}, format="json")
        assert [c[0] for c in fake.calls].count("Customer.create") == 1

    def test_missing_price_config_is_a_clear_400(self, free, fake, settings):
        settings.STRIPE_PRICE_PRO = ""
        r = free.clients[Role.OWNER].post(free.url("billing/checkout/"), {"plan": "pro"}, format="json")
        assert r.status_code == 400 and "No Stripe price configured" in str(r.data)

    def test_stripe_errors_become_readable_400_not_500(self, free, fake):
        fake.fail = True
        r = free.clients[Role.OWNER].post(free.url("billing/checkout/"), {"plan": "pro"}, format="json")
        assert r.status_code == 400 and "Your card was declined." in r.data["detail"]

    def test_portal_needs_a_customer_then_returns_url(self, free, fake):
        o = free.clients[Role.OWNER]
        assert o.post(free.url("billing/portal/")).status_code == 400
        free.ws.stripe_customer_id = "cus_9"; free.ws.save()
        r = o.post(free.url("billing/portal/"))
        assert r.status_code == 200 and r.data["url"].startswith("https://billing.stripe.test")

    def test_billing_page_reports_stripe_mode_and_disables_mock_confirm(self, free, fake):
        o = free.clients[Role.OWNER]
        assert o.get(free.url("billing/")).data["mode"] == "stripe"
        assert o.post(free.url("billing/mock/confirm/"), {"plan": "pro"}, format="json").status_code == 403


@pytest.mark.django_db
class TestBillingSync:
    def test_sync_upgrades_without_any_webhook(self, free, fake):
        free.ws.stripe_customer_id = "cus_123"; free.ws.save()
        fake.subs = [sub("active", "price_pro", "sub_77")]
        r = free.clients[Role.OWNER].post(free.url("billing/sync/"))
        assert r.status_code == 200 and r.data == {"plan": "pro", "subscription_status": "active"}
        free.ws.refresh_from_db()
        assert free.ws.plan == "pro" and free.ws.stripe_subscription_id == "sub_77"

    def test_sync_prefers_live_subscription_over_newer_canceled_one(self, free, fake):
        free.ws.stripe_customer_id = "cus_123"; free.ws.save()
        fake.subs = [sub("canceled", "price_biz", "sub_new"), sub("active", "price_pro", "sub_live")]
        free.clients[Role.OWNER].post(free.url("billing/sync/"))
        free.ws.refresh_from_db()
        assert free.ws.plan == "pro" and free.ws.stripe_subscription_id == "sub_live"

    def test_sync_downgrades_when_only_a_canceled_subscription_remains(self, acme, fake):
        acme.ws.stripe_customer_id = "cus_123"; acme.ws.save()   # acme starts on business
        fake.subs = [sub("canceled", "price_biz", "sub_old")]
        r = acme.clients[Role.OWNER].post(acme.url("billing/sync/"))
        assert r.data["plan"] == "free" and r.data["subscription_status"] == "canceled"

    def test_sync_is_a_noop_without_a_stripe_customer_or_subscriptions(self, free, fake):
        o = free.clients[Role.OWNER]
        assert o.post(free.url("billing/sync/")).data["plan"] == "free"
        assert not [c for c in fake.calls if c[0] == "Subscription.list"]
        free.ws.stripe_customer_id = "cus_123"; free.ws.save()
        fake.subs = []
        assert o.post(free.url("billing/sync/")).data["plan"] == "free"

    def test_sync_works_in_mock_mode_and_is_owner_only(self, free):
        assert free.clients[Role.OWNER].post(free.url("billing/sync/")).data["plan"] == "free"
        assert free.clients[Role.ADMIN].post(free.url("billing/sync/")).status_code == 403

    def test_past_due_keeps_the_plan(self, acme, fake):
        acme.ws.stripe_customer_id = "cus_123"; acme.ws.save()
        fake.subs = [sub("past_due", "price_biz", "sub_x", "business")]
        r = acme.clients[Role.OWNER].post(acme.url("billing/sync/"))
        assert r.data == {"plan": "business", "subscription_status": "past_due"}


@pytest.mark.django_db
class TestStripeWebhookSigned:
    """Uses the real stripe.Webhook.construct_event with a real HMAC signature."""

    def _signed(self, payload: dict, secret: str):
        import stripe

        body = json.dumps(payload)
        import hashlib, hmac, time

        ts = int(time.time())
        sig = hmac.new(secret.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
        return body, f"t={ts},v1={sig}"

    def test_valid_signature_upgrades_and_tampered_body_is_rejected(self, free, client, settings):
        settings.STRIPE_WEBHOOK_SECRET = "whsec_unit_test"
        settings.STRIPE_PRICE_PRO = "price_pro"
        event = {"id": "evt_sig_1", "object": "event", "type": "customer.subscription.updated",
                 "data": {"object": {"id": "sub_1", "object": "subscription", "status": "active", "customer": "cus_x",
                                     "metadata": {"workspace_id": str(free.ws.id), "plan": "pro"},
                                     "items": {"data": [{"price": {"id": "price_pro"}}]}}}}
        body, header = self._signed(event, "whsec_unit_test")
        bad = client.post("/api/billing/stripe-webhook/", body.replace("active", "actiVe"), content_type="application/json", HTTP_STRIPE_SIGNATURE=header)
        assert bad.status_code == 400
        import stripe as _s
        _s.Webhook.construct_event(body, header, "whsec_unit_test")  # sanity: signature itself is valid
        ok = client.post("/api/billing/stripe-webhook/", body, content_type="application/json", HTTP_STRIPE_SIGNATURE=header)
        assert ok.status_code == 200 and ok.json()["status"] == "ok"
        free.ws.refresh_from_db()
        assert free.ws.plan == "pro" and free.ws.subscription_status == "active"


def test_stripe_setup_script_is_idempotent():
    import importlib.util, pathlib

    spec = importlib.util.spec_from_file_location("stripe_setup", pathlib.Path(__file__).parents[1] / "scripts" / "stripe_setup.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    prices = {}

    class Price:
        @staticmethod
        def list(lookup_keys, limit):
            import stripe as real
            return real.convert_to_stripe_object({"object": "list", "data": [prices[k] for k in lookup_keys if k in prices], "has_more": False})

        @staticmethod
        def create(product, unit_amount, currency, recurring, lookup_key, metadata):
            prices[lookup_key] = {"id": f"price_{lookup_key}", "unit_amount": unit_amount}
            return prices[lookup_key]

    class Product:
        n = 0

        @staticmethod
        def create(name, metadata):
            Product.n += 1
            return {"id": f"prod_{Product.n}"}

    fake = SimpleNamespace(Price=Price, Product=Product)
    first = mod.ensure_prices(fake)
    second = mod.ensure_prices(fake)
    assert first == second == {"pro": "price_taskflow_pro_monthly", "business": "price_taskflow_business_monthly"}
    assert Product.n == 2 and prices["taskflow_pro_monthly"]["unit_amount"] == 1200
