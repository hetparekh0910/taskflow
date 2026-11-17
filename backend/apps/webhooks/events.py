from django.db import transaction
from django.utils import timezone


def emit(workspace, event, data):
    """Fan an event out to every subscribed webhook. Runs after the surrounding DB
    transaction commits, so subscribers never hear about rolled-back changes."""

    def _dispatch():
        from .models import Webhook, WebhookDelivery
        from .tasks import deliver_webhook

        for hook in Webhook.objects.filter(workspace=workspace, active=True):
            if not hook.subscribed_to(event):
                continue
            body = {
                "event": event,
                "workspace": workspace.slug,
                "timestamp": timezone.now().isoformat(),
                "data": data,
            }
            delivery = WebhookDelivery.objects.create(workspace=workspace, webhook=hook, event=event, payload=body)
            deliver_webhook.delay(delivery.id)

    transaction.on_commit(_dispatch)
