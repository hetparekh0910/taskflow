from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.workspaces.models import Role
from config.apidocs import Queued, ReportOut
from apps.workspaces.tenancy import WorkspaceScopedMixin

from . import services
from .models import Notification
from .serializers import NotificationSerializer


class NotificationViewSet(
    WorkspaceScopedMixin, mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet
):
    """A user only ever sees their own notifications, within this workspace."""

    queryset = Notification.objects.select_related("issue__project")
    serializer_class = NotificationSerializer
    pagination_class = None
    filter_backends = []
    default_write_role = Role.VIEWER  # marking your own notifications read is allowed for everyone
    http_method_names = ["get", "patch", "post", "head", "options"]

    def get_queryset(self):
        return super().get_queryset().filter(user=self.request.user)[:100] if self.action == "list" else \
            super().get_queryset().filter(user=self.request.user)

    @action(detail=False, methods=["get"])
    def unread_count(self, request, workspace_slug=None):
        return Response({"count": Notification.objects.filter(workspace=request.workspace, user=request.user, read=False).count()})

    @action(detail=False, methods=["post"])
    def mark_all_read(self, request, workspace_slug=None):
        n = Notification.objects.filter(workspace=request.workspace, user=request.user, read=False).update(read=True)
        return Response({"updated": n})


class WeeklyReportView(WorkspaceScopedMixin, APIView):
    default_read_role = Role.MEMBER
    default_write_role = Role.ADMIN

    @extend_schema(parameters=[OpenApiParameter("days", int, description="1-90, default 7")], responses=ReportOut, summary="Activity report for the last N days")
    def get(self, request, workspace_slug):
        days = min(int(request.query_params.get("days", 7)), 90)
        return Response(services.weekly_report(request.workspace, days))

    @extend_schema(request=None, responses={202: Queued}, summary="Queue the report email to owners/admins now (same job Celery beat runs weekly)")
    def post(self, request, workspace_slug):
        """Queue the report email to owners/admins now (the same job Celery beat runs weekly)."""
        from .tasks import send_weekly_report

        send_weekly_report.delay(request.workspace.id)
        return Response({"queued": True}, status=202)
