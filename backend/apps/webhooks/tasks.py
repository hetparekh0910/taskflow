import hashlib
import hmac
import ipaddress
import json
import socket
import time
from datetime import timedelta
from urllib.parse import urlparse

import requests
from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .models import WebhookDelivery


def sign(secret: str, timestamp: str, body: str) -> str:
    """HMAC-SHA256 over '<timestamp>.<body>'. Receivers recompute and compare in constant time."""
    return hmac.new(secret.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256).hexdigest()


def assert_url_is_safe(url: str):
    """Basic SSRF guard: only http(s), and no private/loopback/link-local targets in production."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Webhook URL must be http(s).")
    if settings.WEBHOOK_ALLOW_PRIVATE:
        return
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as e:
        raise ValueError(f"Cannot resolve host: {e}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError("Webhook URL resolves to a private or reserved address.")


def backoff_seconds(attempt: int) -> int:
    return min(30 * (2 ** (attempt - 1)), 3600)  # 30s, 60s, 2m, 4m ... capped at 1h


@shared_task
def deliver_webhook(delivery_id: int):
    delivery = WebhookDelivery.objects.select_related("webhook").filter(pk=delivery_id).first()
    if delivery is None or delivery.success:
        return
    hook = delivery.webhook
    if not hook.active:
        return
    now = timezone.now()
    if delivery.next_retry_at and delivery.next_retry_at > now + timedelta(seconds=2):
        return  # a scheduled retry that is not due yet (e.g. picked up early by the beat sweep)

    body = json.dumps(delivery.payload, separators=(",", ":"), sort_keys=True, default=str)
    ts = str(int(time.time()))
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "TaskFlow-Webhooks/1.0",
        "X-TaskFlow-Event": delivery.event,
        "X-TaskFlow-Delivery": str(delivery.id),
        "X-TaskFlow-Timestamp": ts,
        "X-TaskFlow-Signature": f"sha256={sign(hook.secret, ts, body)}",
    }
    delivery.attempts += 1
    try:
        assert_url_is_safe(hook.url)
        resp = requests.post(
            hook.url, data=body, headers=headers, timeout=settings.WEBHOOK_TIMEOUT_SECONDS, allow_redirects=False
        )
        delivery.status_code = resp.status_code
        delivery.response_body = resp.text[:2000]
        delivery.success = 200 <= resp.status_code < 300
        delivery.error = "" if delivery.success else f"HTTP {resp.status_code}"
    except Exception as exc:  # network error, timeout, blocked URL ...
        delivery.success = False
        delivery.status_code = None
        delivery.error = str(exc)[:500]

    if delivery.success:
        delivery.delivered_at = timezone.now()
        delivery.next_retry_at = None
    elif delivery.attempts < settings.WEBHOOK_MAX_ATTEMPTS:
        delay = backoff_seconds(delivery.attempts)
        delivery.next_retry_at = timezone.now() + timedelta(seconds=delay)
    else:
        delivery.next_retry_at = None
    delivery.save()

    if not delivery.success and delivery.next_retry_at and not settings.CELERY_TASK_ALWAYS_EAGER:
        deliver_webhook.apply_async((delivery.id,), countdown=backoff_seconds(delivery.attempts))


@shared_task
def retry_failed_deliveries():
    """Beat safety net: re-enqueue anything whose retry time has passed (e.g. after a worker restart)."""
    due = WebhookDelivery.objects.filter(
        success=False, next_retry_at__isnull=False, next_retry_at__lte=timezone.now()
    ).values_list("id", flat=True)[:200]
    for delivery_id in due:
        deliver_webhook.delay(delivery_id)
    return len(due)
