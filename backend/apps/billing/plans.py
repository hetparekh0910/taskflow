"""Plan catalogue and limit enforcement. None = unlimited."""
from dataclasses import dataclass

from django.conf import settings
from rest_framework.exceptions import APIException


@dataclass(frozen=True)
class PlanSpec:
    key: str
    name: str
    price_usd: int  # per month
    max_members: int | None
    max_projects: int | None
    max_storage_mb: int | None
    webhooks: bool
    audit_log_days: int | None  # retention shown in UI


PLANS = {
    "free": PlanSpec("free", "Free", 0, 3, 2, 100, False, 7),
    "pro": PlanSpec("pro", "Pro", 12, 15, 10, 5 * 1024, True, 90),
    "business": PlanSpec("business", "Business", 49, None, None, 50 * 1024, True, None),
}


class PlanLimitExceeded(APIException):
    """402 with a structured payload the UI uses to show an upgrade prompt."""

    status_code = 402
    default_code = "plan_limit"
    default_detail = "Plan limit reached. Upgrade to continue."

    def __init__(self, payload=None):
        self.payload = payload or {"detail": self.default_detail, "code": "plan_limit"}
        super().__init__(self.payload.get("detail"), self.default_code)


def spec_for(workspace) -> PlanSpec:
    return PLANS.get(workspace.plan, PLANS["free"])


def usage_for(workspace) -> dict:
    from django.db.models import Sum

    from apps.projects.models import Attachment, Project
    from apps.workspaces.models import Invitation, Membership

    storage = Attachment.objects.filter(workspace=workspace).aggregate(s=Sum("size"))["s"] or 0
    return {
        "members": Membership.objects.filter(workspace=workspace).count(),
        "pending_invites": Invitation.objects.filter(workspace=workspace, accepted_at__isnull=True).count(),
        "projects": Project.objects.filter(workspace=workspace, archived=False).count(),
        "storage_mb": round(storage / (1024 * 1024), 2),
    }


def enforce(workspace, resource: str, adding: float = 1):
    """Raise PlanLimitExceeded if adding `adding` of `resource` would exceed the plan."""
    spec = spec_for(workspace)
    usage = usage_for(workspace)
    limit, used = {
        "members": (spec.max_members, usage["members"] + usage["pending_invites"]),
        "projects": (spec.max_projects, usage["projects"]),
        "storage": (spec.max_storage_mb, usage["storage_mb"]),
    }[resource]
    if limit is not None and used + adding > limit:
        raise PlanLimitExceeded(
            {
                "detail": f"Your {spec.name} plan allows {limit} {resource.replace('_', ' ')}. Upgrade to add more.",
                "code": "plan_limit",
                "resource": resource,
                "limit": limit,
                "plan": spec.key,
            }
        )


def price_id_for(plan_key: str) -> str:
    return {"pro": settings.STRIPE_PRICE_PRO, "business": settings.STRIPE_PRICE_BUSINESS}.get(plan_key, "")


def plan_for_price(price_id: str) -> str | None:
    for key in ("pro", "business"):
        if price_id and price_id == price_id_for(key):
            return key
    return None
