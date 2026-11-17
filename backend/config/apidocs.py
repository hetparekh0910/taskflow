"""Small helpers so hand-written APIViews show up in the OpenAPI schema with real request/response shapes."""
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers as s

Ok = inline_serializer("Ok", {"detail": s.CharField()})
PlanSpecOut = inline_serializer("PlanSpec", {
    "key": s.CharField(), "name": s.CharField(), "price_usd": s.IntegerField(),
    "max_members": s.IntegerField(allow_null=True), "max_projects": s.IntegerField(allow_null=True),
    "max_storage_mb": s.IntegerField(allow_null=True), "webhooks": s.BooleanField(), "audit_log_days": s.IntegerField(allow_null=True),
})
BillingOut = inline_serializer("Billing", {
    "plan": s.CharField(), "subscription_status": s.CharField(), "limits": PlanSpecOut,
    "usage": inline_serializer("Usage", {"members": s.IntegerField(), "pending_invites": s.IntegerField(), "projects": s.IntegerField(), "storage_mb": s.FloatField()}),
    "plans": type(PlanSpecOut)(many=True), "mode": s.ChoiceField(["mock", "stripe"]), "can_manage": s.BooleanField(),
})
PlanIn = inline_serializer("PlanChoice", {"plan": s.ChoiceField(["pro", "business"])})
RedirectOut = inline_serializer("Redirect", {"url": s.CharField(), "mock": s.BooleanField()})
PlanState = inline_serializer("PlanState", {"plan": s.CharField(), "subscription_status": s.CharField()})
DashboardOut = inline_serializer("DashboardData", {
    "totals": s.DictField(child=s.IntegerField()), "by_status": s.ListField(child=s.DictField()), "by_priority": s.ListField(child=s.DictField()),
    "by_type": s.ListField(child=s.DictField()), "workload": s.ListField(child=s.DictField()), "flow": s.ListField(child=s.DictField()),
    "velocity": s.ListField(child=s.DictField()),
})
SearchOut = inline_serializer("SearchResults", {"issues": s.ListField(child=s.DictField()), "projects": s.ListField(child=s.DictField())})
ReportOut = inline_serializer("WeeklyReport", {
    "workspace": s.CharField(), "period_days": s.IntegerField(), "generated_at": s.DateTimeField(), "totals": s.DictField(child=s.IntegerField()),
    "projects": s.ListField(child=s.DictField()), "top_contributors": s.ListField(child=s.DictField()), "active_sprints": s.ListField(child=s.DictField()),
})
Queued = inline_serializer("Queued", {"queued": s.BooleanField()})
InviteInfo = inline_serializer("InviteInfo", {"email": s.EmailField(), "workspace_name": s.CharField(), "role": s.CharField()})
TokenIn = inline_serializer("InviteToken", {"token": s.CharField()})
StripeEventOut = inline_serializer("StripeWebhookResult", {"status": s.CharField()})

__all__ = [n for n in dir() if not n.startswith("_")]
