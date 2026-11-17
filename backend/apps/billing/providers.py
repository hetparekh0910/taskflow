"""Billing providers behind one interface.

StripeProvider talks to Stripe (test or live keys). MockProvider simulates the
same flow with no account or network, so the whole product demos end-to-end
before real keys exist. `get_provider()` picks one based on STRIPE_SECRET_KEY.
"""
import secrets

from django.conf import settings
from rest_framework.exceptions import ValidationError

from . import plans


def _plain(obj):
    """Stripe SDK objects -> plain dicts (tests and webhooks already use dicts)."""
    return obj.to_dict() if hasattr(obj, "to_dict") else obj


class BaseProvider:
    mode = "base"

    def create_checkout(self, workspace, plan_key, user): ...
    def create_portal(self, workspace): ...
    def cancel(self, workspace): ...
    def latest_subscription(self, workspace):
        """Ask the provider for the workspace's current subscription (None if there is none)."""
        return None


class MockProvider(BaseProvider):
    mode = "mock"

    def create_checkout(self, workspace, plan_key, user):
        token = secrets.token_urlsafe(12)
        return {
            # Relative on purpose: the simulated checkout lives in the same app, so it must work
            # on whatever host the user is on (localhost, 127.0.0.1, a preview URL...).
            "url": f"/w/{workspace.slug}/billing/mock-checkout?plan={plan_key}&session={token}",
            "mock": True,
        }

    def create_portal(self, workspace):
        return {"url": f"/w/{workspace.slug}/billing", "mock": True}

    def cancel(self, workspace):
        workspace.plan = "free"
        workspace.subscription_status = "canceled"
        workspace.stripe_subscription_id = ""
        workspace.save(update_fields=["plan", "subscription_status", "stripe_subscription_id"])


class StripeProvider(BaseProvider):
    mode = "stripe"

    def __init__(self):
        import stripe

        stripe.api_key = settings.STRIPE_SECRET_KEY
        self.stripe = stripe

    def _customer(self, workspace, user):
        if workspace.stripe_customer_id:
            return workspace.stripe_customer_id
        customer = self.stripe.Customer.create(
            email=user.email, name=workspace.name, metadata={"workspace_id": str(workspace.id)}
        )
        workspace.stripe_customer_id = customer["id"]
        workspace.save(update_fields=["stripe_customer_id"])
        return customer["id"]

    def _call(self, fn, *args, **kwargs):
        """Run a Stripe call, turning Stripe errors into readable 400s instead of 500s."""
        try:
            return fn(*args, **kwargs)
        except self.stripe.StripeError as exc:
            msg = getattr(exc, "user_message", None) or str(exc)
            raise ValidationError({"detail": f"Stripe error: {msg}"})

    def create_checkout(self, workspace, plan_key, user):
        price = plans.price_id_for(plan_key)
        if not price:
            raise ValidationError({"plan": f"No Stripe price configured for '{plan_key}'."})
        base = f"{settings.FRONTEND_URL}/w/{workspace.slug}/billing"
        session = self._call(
            self.stripe.checkout.Session.create,
            mode="subscription",
            customer=self._customer(workspace, user),
            line_items=[{"price": price, "quantity": 1}],
            success_url=f"{base}?checkout=success",
            cancel_url=f"{base}?checkout=cancelled",
            client_reference_id=str(workspace.id),
            metadata={"workspace_id": str(workspace.id), "plan": plan_key},
            subscription_data={"metadata": {"workspace_id": str(workspace.id), "plan": plan_key}},
        )
        return {"url": session["url"], "mock": False}

    def create_portal(self, workspace):
        if not workspace.stripe_customer_id:
            raise ValidationError("No billing account yet. Subscribe to a plan first.")
        session = self._call(
            self.stripe.billing_portal.Session.create,
            customer=workspace.stripe_customer_id,
            return_url=f"{settings.FRONTEND_URL}/w/{workspace.slug}/billing",
        )
        return {"url": session["url"], "mock": False}

    def latest_subscription(self, workspace):
        if not workspace.stripe_customer_id:
            return None
        listing = self._call(self.stripe.Subscription.list, customer=workspace.stripe_customer_id, status="all", limit=10)
        # Stripe objects are not dicts (no .get); convert to plain dicts for the rest of the app.
        subs = [_plain(x) for x in (listing["data"] if "data" in listing else [])]
        # Stripe returns newest first: prefer a live subscription, otherwise report the latest state (e.g. canceled).
        live = [x for x in subs if x.get("status") in ("active", "trialing")]
        return (live or subs or [None])[0]

    def cancel(self, workspace):
        if workspace.stripe_subscription_id:
            self._call(self.stripe.Subscription.cancel, workspace.stripe_subscription_id)
        # Plan downgrade itself is applied by the customer.subscription.deleted webhook.


def get_provider() -> BaseProvider:
    return StripeProvider() if settings.STRIPE_SECRET_KEY else MockProvider()
