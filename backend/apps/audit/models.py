from django.conf import settings
from django.db import models

from apps.workspaces.tenancy import TenantModel


class AuditLog(TenantModel):
    class Action(models.TextChoices):
        CREATE = "create", "Created"
        UPDATE = "update", "Updated"
        DELETE = "delete", "Deleted"

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=10, choices=Action.choices)
    model = models.CharField(max_length=60)
    object_id = models.CharField(max_length=40)
    object_repr = models.CharField(max_length=255)
    # {"field": {"old": ..., "new": ...}} for updates; snapshot for create/delete.
    changes = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["workspace", "model", "object_id"])]
