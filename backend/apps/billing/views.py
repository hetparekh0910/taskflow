import json
import logging

from django.conf import settings
from django.db import IntegrityError, transaction
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.workspaces.models import Role, Workspace
from apps.workspaces.tenancy import WorkspaceScopedMixin

from . import plans
from .models import StripeEvent
from .providers import MockProvider, get_provider

log = logging.getLogger(__name__)


def _spec_dict(spec):
    return {
        "key": spec.key, "name": spec.name, "price_usd": spec.price_usd,
        "max_members": spec.max_members, "max_projects": spec.max_projects,
        "max_storage_mb": spec.max_storage_mb, "webhooks": spec.webhooks,
        "audit_log_days": spec.audit_log_days,
    }
from drf_spectacular.utils import extend_schema

from config.apidocs import *  # noqa


class BillingView(WorkspaceScopedMixin, APIView):
    """GET: current plan, usage vs limits and the plan catalogue (any member can see)."""

    @extend_schema(responses=BillingOut, summary="Current plan, usage vs limits and the plan catalogue")
    def get(self, request, workspace_slug):
        ws = request.workspace
        provider = get_provider()
        return Response(
            {
                "plan": ws.plan,
                "subscription_status": ws.subscription_status,
                "limits": _spec_dict(plans.spec_for(ws)),
                "usage": plans.usage_for(ws),
                "plans": [_spec_dict(p) for p in plans.PLANS.values()],
                "mode": provider.mode,
                "can_manage": request.membership.role == Role.OWNER,
            }
        )


class OwnerOnlyBilling(WorkspaceScopedMixin, APIView):
    default_write_role = Role.OWNER
    default_read_role = Role.OWNER


class CheckoutView(OwnerOnlyBilling):
    @extend_schema(request=PlanIn, responses=RedirectOut, summary="Start a subscription checkout (Stripe, or simulated when no keys are set)")
    def post(self, request, workspace_slug):
        plan = request.data.get("plan")
        if plan not in ("pro", "business"):
            raise ValidationError({"plan": "Choose 'pro' or 'business'."})
        if request.workspace.plan == plan:
            raise ValidationError({"plan": "You are already on this plan."})
        return Response(get_provider().create_checkout(request.workspace, plan, request.user))


class PortalView(OwnerOnlyBilling):
    @extend_schema(request=None, responses=RedirectOut, summary="Open the Stripe customer portal (payment method, invoices)")
    def post(self, request, workspace_slug):
        return Response(get_provider().create_portal(request.workspace))


class CancelView(OwnerOnlyBilling):
    @extend_schema(request=None, responses=PlanState, summary="Cancel the subscription and return to Free")
    def post(self, request, workspace_slug):
        if request.workspace.plan == "free":
            raise ValidationError("You are already on the Free plan.")
        get_provider().cancel(request.workspace)
        request.workspace.refresh_from_db()
        return Response({"plan": request.workspace.plan, "subscription_status": request.workspace.subscription_status})


class SyncView(OwnerOnlyBilling):
    """Pull the subscription state straight from Stripe. The checkout success page calls this so the
    plan upgrades immediately even if Stripe's webhook is late, blocked or not configured (e.g. localhost)."""

    @extend_schema(request=None, responses=PlanState, summary="Refresh plan and status from the payment provider")
    def post(self, request, workspace_slug):
        ws = request.workspace
        sub = get_provider().latest_subscription(ws)
        if sub is not None:
            _apply_subscription(ws, sub)
            ws.refresh_from_db()
        return Response({"plan": ws.plan, "subscription_status": ws.subscription_status})


class MockConfirmView(OwnerOnlyBilling):
    """Mock mode only: the 'pay' button on the fake checkout page lands here and upgrades the workspace.
    Disabled as soon as real Stripe keys are configured."""

    @extend_schema(request=PlanIn, responses=PlanState, summary="Simulated payment confirmation (disabled when Stripe keys are configured)")
    def post(self, request, workspace_slug):
        if not isinstance(get_provider(), MockProvider):
            raise PermissionDenied("Mock checkout is disabled when Stripe is configured.")
        plan = request.data.get("plan")
        if plan not in ("pro", "business"):
            raise ValidationError({"plan": "Invalid plan."})
        ws = request.workspace
        ws.plan = plan
        ws.subscription_status = "active"
        ws.stripe_subscription_id = f"mock_sub_{ws.id}"
        ws.save(update_fields=["plan", "subscription_status", "stripe_subscription_id"])
        return Response({"plan": ws.plan, "subscription_status": ws.subscription_status})


# --------------------------------------------------------------------------- Stripe webhook


def _apply_subscription(workspace, subscription):
    status = subscription.get("status", "")
    items = (subscription.get("items") or {}).get("data") or []
    price_id = items[0]["price"]["id"] if items else ""
    plan = plans.plan_for_price(price_id) or (subscription.get("metadata") or {}).get("plan")
    workspace.stripe_subscription_id = subscription.get("id", "")
    workspace.subscription_status = status
    if status in ("active", "trialing") and plan in ("pro", "business"):
        workspace.plan = plan
    elif status in ("canceled", "unpaid", "incomplete_expired"):
        workspace.plan = "free"
    # past_due keeps the current plan; Stripe retries the card first.
    workspace.save(update_fields=["plan", "subscription_status", "stripe_subscription_id"])


def _workspace_from(obj):
    meta = obj.get("metadata") or {}
    wid = meta.get("workspace_id") or obj.get("client_reference_id")
    if wid and str(wid).isdigit():
        ws = Workspace.objects.filter(pk=int(wid)).first()
        if ws:
            return ws
    cid = obj.get("customer")
    return Workspace.objects.filter(stripe_customer_id=cid).first() if cid else None


def handle_event(event: dict) -> str:
    etype, obj = event["type"], event["data"]["object"]
    ws = _workspace_from(obj)
    if ws is None:
        return "no-workspace"
    if etype == "checkout.session.completed":
        if obj.get("customer") and not ws.stripe_customer_id:
            ws.stripe_customer_id = obj["customer"]
        if obj.get("subscription"):
            ws.stripe_subscription_id = obj["subscription"]
            plan = (obj.get("metadata") or {}).get("plan")
            if plan in ("pro", "business"):
                ws.plan = plan
                ws.subscription_status = "active"
        ws.save(update_fields=["stripe_customer_id", "stripe_subscription_id", "plan", "subscription_status"])
    elif etype in ("customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"):
        _apply_subscription(ws, obj)
    elif etype == "invoice.payment_failed":
        ws.subscription_status = "past_due"
        ws.save(update_fields=["subscription_status"])
    else:
        return "ignored"
    return "ok"


class StripeWebhookView(APIView):
    """Public endpoint called by Stripe. Verifies the signature, then applies the event once."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []

    @extend_schema(request=None, responses=StripeEventOut, summary="Stripe webhook receiver (signature-verified, idempotent)")
    def post(self, request):
        payload = request.body
        if settings.STRIPE_WEBHOOK_SECRET:
            import stripe

            try:
                # Verify the signature, then use the verified raw payload as plain JSON
                # (the SDK's event object differs between stripe-python versions).
                stripe.Webhook.construct_event(
                    payload, request.META.get("HTTP_STRIPE_SIGNATURE", ""), settings.STRIPE_WEBHOOK_SECRET
                )
                event = json.loads(payload)
            except Exception as exc:
                log.warning("Rejected Stripe webhook: %s", exc)
                return Response({"detail": "Invalid signature."}, status=400)
        else:
            # No secret configured (local/mock). Never trust unsigned events in production.
            if not settings.DEBUG:
                return Response({"detail": "Webhook secret not configured."}, status=400)
            event = json.loads(payload or b"{}")
        if "id" not in event or "type" not in event:
            return Response({"detail": "Malformed event."}, status=400)
        try:
            with transaction.atomic():
                StripeEvent.objects.create(event_id=event["id"], type=event["type"])
                result = handle_event(event)
        except IntegrityError:
            return Response({"status": "duplicate"})  # already processed: idempotent
        return Response({"status": result})
