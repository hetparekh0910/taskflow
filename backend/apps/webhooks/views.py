from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.billing import plans
from apps.billing.plans import PlanLimitExceeded
from apps.workspaces.models import Role
from apps.workspaces.tenancy import WorkspaceScopedMixin

from .events import emit
from .models import EVENTS, Webhook, WebhookDelivery
from .serializers import WebhookDeliverySerializer, WebhookSerializer
from .tasks import deliver_webhook


class WebhookViewSet(WorkspaceScopedMixin, viewsets.ModelViewSet):
    """Admin-only. Webhooks are a Pro+ feature."""

    queryset = Webhook.objects.all()
    serializer_class = WebhookSerializer
    default_read_role = Role.ADMIN
    default_write_role = Role.ADMIN
    pagination_class = None
    filter_backends = []

    def perform_create(self, serializer):
        if not plans.spec_for(self.request.workspace).webhooks:
            raise PlanLimitExceeded(
                {"detail": "Webhooks are available on Pro and Business plans.", "code": "plan_limit",
                 "resource": "webhooks", "plan": self.request.workspace.plan}
            )
        super().perform_create(serializer)

    @action(detail=False, methods=["get"])
    def events(self, request, workspace_slug=None):
        return Response(EVENTS)

    @action(detail=True, methods=["post"])
    def test(self, request, workspace_slug=None, pk=None):
        """Send a synthetic `ping` delivery so the receiver can verify wiring and signature."""
        hook = self.get_object()
        from django.utils import timezone

        delivery = WebhookDelivery.objects.create(
            workspace=request.workspace,
            webhook=hook,
            event="ping",
            payload={"event": "ping", "workspace": request.workspace.slug, "timestamp": timezone.now().isoformat(),
                     "data": {"message": "Hello from TaskFlow"}},
        )
        deliver_webhook(delivery.id)  # run inline so the UI gets the result immediately
        delivery.refresh_from_db()
        return Response(WebhookDeliverySerializer(delivery).data)


class WebhookDeliveryViewSet(WorkspaceScopedMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = WebhookDelivery.objects.all()
    serializer_class = WebhookDeliverySerializer
    default_read_role = Role.ADMIN
    default_write_role = Role.ADMIN
    filterset_fields = ["webhook", "success", "event"]

    @action(detail=True, methods=["post"])
    def redeliver(self, request, workspace_slug=None, pk=None):
        d = self.get_object()
        d.success = False
        d.attempts = 0
        d.next_retry_at = None
        d.save(update_fields=["success", "attempts", "next_retry_at"])
        deliver_webhook(d.id)
        d.refresh_from_db()
        return Response(WebhookDeliverySerializer(d).data)
