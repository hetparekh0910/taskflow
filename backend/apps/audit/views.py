from rest_framework import mixins, viewsets

from apps.workspaces.models import Role
from apps.workspaces.tenancy import WorkspaceScopedMixin

from .models import AuditLog
from .serializers import AuditLogSerializer


class AuditLogViewSet(WorkspaceScopedMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """Read-only. Admins and owners only; the log can never be edited through the API."""

    queryset = AuditLog.objects.select_related("actor")
    serializer_class = AuditLogSerializer
    default_read_role = Role.ADMIN
    filterset_fields = ["model", "action", "actor", "object_id"]
    search_fields = ["object_repr"]
