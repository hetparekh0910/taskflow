from django.conf import settings
from django.db import models

from apps.workspaces.tenancy import TenantModel


class Notification(TenantModel):
    class Kind(models.TextChoices):
        ASSIGNED = "assigned", "Assigned to you"
        MENTION = "mention", "Mentioned you"
        COMMENT = "comment", "New comment"
        STATUS = "status", "Status changed"
        SPRINT = "sprint", "Sprint update"
        SYSTEM = "system", "System"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.SYSTEM)
    message = models.CharField(max_length=300)
    issue = models.ForeignKey("projects.Issue", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    read = models.BooleanField(default=False)
    emailed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
