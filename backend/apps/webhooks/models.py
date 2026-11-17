import secrets

from django.db import models

from apps.workspaces.tenancy import TenantModel

EVENTS = [
    "issue.created",
    "issue.updated",
    "issue.moved",
    "issue.deleted",
    "comment.created",
    "sprint.started",
    "sprint.closed",
    "project.created",
    "member.joined",
]


def _secret():
    return "whsec_" + secrets.token_hex(20)


class Webhook(TenantModel):
    url = models.URLField(max_length=500)
    secret = models.CharField(max_length=80, default=_secret)
    events = models.JSONField(default=list, help_text="Subscribed event names; ['*'] = all")
    active = models.BooleanField(default=True)
    description = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]

    def subscribed_to(self, event):
        return self.active and ("*" in self.events or event in self.events)


class WebhookDelivery(TenantModel):
    webhook = models.ForeignKey(Webhook, on_delete=models.CASCADE, related_name="deliveries")
    event = models.CharField(max_length=40)
    payload = models.JSONField(default=dict)
    attempts = models.PositiveSmallIntegerField(default=0)
    success = models.BooleanField(default=False)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.TextField(blank=True)
    error = models.TextField(blank=True)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
