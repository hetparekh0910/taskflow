import hashlib
import hmac
import json

import pytest
import requests

from apps.notifications.models import Notification
from apps.webhooks.models import Webhook, WebhookDelivery
from apps.webhooks.tasks import deliver_webhook, sign
from apps.workspaces.models import Role


class FakeResp:
    def __init__(self, code=200, text="ok"):
        self.status_code, self.text = code, text


@pytest.fixture
def hook(acme):
    r = acme.clients[Role.ADMIN].post(acme.url("webhooks/"), {"url": "https://example.com/hook", "events": ["*"]}, format="json")
    assert r.status_code == 201, r.data
    return Webhook.objects.get(pk=r.data["id"])


@pytest.mark.django_db
class TestWebhooks:
    def test_event_delivery_with_valid_hmac_signature(self, acme, hook, monkeypatch):
        calls = []
        monkeypatch.setattr(requests, "post", lambda url, **kw: calls.append((url, kw)) or FakeResp())
        issue = acme.make_issue("hello")
        assert [c for c in calls if json.loads(c[1]["data"])["event"] == "issue.created"]
        url, kw = next(c for c in calls if json.loads(c[1]["data"])["event"] == "issue.created")
        h = kw["headers"]
        expected = hmac.new(hook.secret.encode(), f"{h['X-TaskFlow-Timestamp']}.{kw['data']}".encode(), hashlib.sha256).hexdigest()
        assert h["X-TaskFlow-Signature"] == f"sha256={expected}"
        assert kw["allow_redirects"] is False
        body = json.loads(kw["data"])
        assert body["data"]["key"] == issue.key and body["workspace"] == acme.ws.slug
        d = WebhookDelivery.objects.filter(event="issue.created").get()
        assert d.success and d.attempts == 1 and d.status_code == 200

    def test_only_subscribed_events_and_inactive_hooks_skipped(self, acme, hook, monkeypatch):
        calls = []
        monkeypatch.setattr(requests, "post", lambda url, **kw: calls.append(json.loads(kw["data"])["event"]) or FakeResp())
        hook.events = ["issue.moved"]; hook.save()
        i = acme.make_issue("x")
        assert calls == []
        acme.clients[Role.MEMBER].post(acme.url(f"issues/{i.id}/move/"), {"status": acme.status("Done").id}, format="json")
        assert calls == ["issue.moved"]
        hook.active = False; hook.save()
        acme.clients[Role.MEMBER].post(acme.url(f"issues/{i.id}/move/"), {"status": acme.status("To Do").id}, format="json")
        assert calls == ["issue.moved"]

    def test_failure_is_recorded_and_scheduled_for_retry_with_backoff(self, acme, hook, monkeypatch):
        monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp(500, "boom"))
        acme.make_issue("x")
        d = WebhookDelivery.objects.filter(event="issue.created").get()
        assert not d.success and d.attempts == 1 and d.status_code == 500 and d.next_retry_at is not None

    def test_network_error_and_gives_up_after_max_attempts(self, acme, hook, monkeypatch, settings):
        def boom(*a, **k):
            raise requests.ConnectionError("down")

        monkeypatch.setattr(requests, "post", boom)
        settings.WEBHOOK_MAX_ATTEMPTS = 2
        acme.make_issue("x")
        d = WebhookDelivery.objects.filter(event="issue.created").get()
        assert "down" in d.error
        from django.utils import timezone

        WebhookDelivery.objects.filter(pk=d.pk).update(next_retry_at=timezone.now())
        deliver_webhook(d.id)
        d.refresh_from_db()
        assert d.attempts == 2 and not d.success and d.next_retry_at is None  # exhausted

    def test_retry_sweep_redelivers_due_failures(self, acme, hook, monkeypatch):
        from django.utils import timezone

        from apps.webhooks.tasks import retry_failed_deliveries

        monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp(503))
        acme.make_issue("x")
        d = WebhookDelivery.objects.filter(event="issue.created").get()
        monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp(200))
        WebhookDelivery.objects.filter(pk=d.pk).update(next_retry_at=timezone.now())
        assert retry_failed_deliveries() == 1
        d.refresh_from_db()
        assert d.success and d.attempts == 2

    def test_test_ping_and_redeliver_endpoints(self, acme, hook, monkeypatch):
        monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp(200))
        r = acme.clients[Role.ADMIN].post(acme.url(f"webhooks/{hook.id}/test/"))
        assert r.status_code == 200 and r.data["event"] == "ping" and r.data["success"]
        monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp(500))
        acme.make_issue("x")
        d = WebhookDelivery.objects.filter(event="issue.created").get()
        monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp(200))
        r = acme.clients[Role.ADMIN].post(acme.url(f"webhook-deliveries/{d.id}/redeliver/"))
        assert r.data["success"] is True

    def test_ssrf_guard_blocks_private_targets_in_production(self, acme, settings):
        settings.WEBHOOK_ALLOW_PRIVATE = False
        for url in ["http://127.0.0.1:8000/x", "http://localhost/x", "http://169.254.169.254/latest/meta-data", "ftp://example.com/x"]:
            r = acme.clients[Role.ADMIN].post(acme.url("webhooks/"), {"url": url, "events": ["*"]}, format="json")
            assert r.status_code == 400, url

    def test_validation_and_plan_gate(self, acme):
        a = acme.clients[Role.ADMIN]
        assert a.post(acme.url("webhooks/"), {"url": "https://e.com", "events": ["nope"]}, format="json").status_code == 400
        assert a.post(acme.url("webhooks/"), {"url": "https://e.com", "events": []}, format="json").status_code == 400
        acme.ws.plan = "free"; acme.ws.save()
        r = a.post(acme.url("webhooks/"), {"url": "https://e.com", "events": ["*"]}, format="json")
        assert r.status_code == 402 and r.data["resource"] == "webhooks"

    def test_signature_helper_matches_spec(self):
        assert sign("k", "123", "{}") == hmac.new(b"k", b"123.{}", hashlib.sha256).hexdigest()


@pytest.mark.django_db
class TestNotifications:
    def test_assignment_notifies_assignee_and_queues_email(self, acme):
        from django.core import mail

        issue = acme.make_issue("x", as_role=Role.MEMBER, assignee=acme.users[Role.ADMIN].id)
        n = Notification.objects.get(user=acme.users[Role.ADMIN], kind="assigned")
        assert issue.key in n.message
        assert any(acme.users[Role.ADMIN].email in m.to for m in mail.outbox)

    def test_no_self_notification(self, acme):
        acme.make_issue("x", as_role=Role.MEMBER, assignee=acme.users[Role.MEMBER].id)
        assert Notification.objects.count() == 0

    def test_comment_and_mention_notifications_without_duplicates(self, acme):
        issue = acme.make_issue("x", as_role=Role.MEMBER, assignee=acme.users[Role.ADMIN].id)
        Notification.objects.all().delete()
        handle = acme.users[Role.ADMIN].email.split("@")[0]
        acme.clients[Role.MEMBER].post(acme.url("comments/"), {"issue": issue.id, "body": f"@{handle} please look"}, format="json")
        kinds = list(Notification.objects.filter(user=acme.users[Role.ADMIN]).values_list("kind", flat=True))
        assert kinds == ["comment"]  # assignee already told about the comment; mention not duplicated
        viewer_handle = acme.users[Role.VIEWER].email.split("@")[0]
        acme.clients[Role.MEMBER].post(acme.url("comments/"), {"issue": issue.id, "body": f"fyi @{viewer_handle}"}, format="json")
        assert Notification.objects.filter(user=acme.users[Role.VIEWER], kind="mention").count() == 1

    def test_users_only_see_their_own_notifications_and_can_mark_read(self, acme):
        acme.make_issue("x", as_role=Role.MEMBER, assignee=acme.users[Role.ADMIN].id)
        assert acme.clients[Role.MEMBER].get(acme.url("notifications/")).data == []
        admin = acme.clients[Role.ADMIN]
        assert len(admin.get(acme.url("notifications/")).data) == 1
        assert admin.get(acme.url("notifications/unread_count/")).data["count"] == 1
        nid = admin.get(acme.url("notifications/")).data[0]["id"]
        assert acme.clients[Role.MEMBER].patch(acme.url(f"notifications/{nid}/"), {"read": True}, format="json").status_code == 404
        assert admin.patch(acme.url(f"notifications/{nid}/"), {"read": True}, format="json").status_code == 200
        assert admin.post(acme.url("notifications/mark_all_read/")).status_code == 200

    def test_status_change_notifies_reporter(self, acme):
        issue = acme.make_issue("x", as_role=Role.MEMBER)
        acme.clients[Role.ADMIN].post(acme.url(f"issues/{issue.id}/move/"), {"status": acme.status("Done").id}, format="json")
        assert Notification.objects.filter(user=acme.users[Role.MEMBER], kind="status").exists()


@pytest.mark.django_db
class TestReports:
    def test_weekly_report_and_email_job(self, acme):
        from django.core import mail

        from apps.notifications.tasks import send_weekly_reports

        acme.make_issue("a"); acme.make_issue("b", status=acme.status("Done").id, assignee=acme.users[Role.ADMIN].id)
        r = acme.clients[Role.MEMBER].get(acme.url("reports/weekly/")).data
        assert r["totals"]["created"] == 2 and r["totals"]["resolved"] == 1 and r["projects"][0]["key"] == "WEB"
        assert r["top_contributors"][0]["resolved"] == 1
        mail.outbox.clear()
        assert send_weekly_reports() == 1
        recipients = {a for m in mail.outbox for a in m.to}
        assert acme.owner.email in recipients and acme.users[Role.ADMIN].email in recipients
        assert acme.users[Role.MEMBER].email not in recipients
        assert acme.clients[Role.ADMIN].post(acme.url("reports/weekly/")).status_code == 202
        assert acme.clients[Role.MEMBER].post(acme.url("reports/weekly/")).status_code == 403


@pytest.mark.django_db(transaction=True)
def test_rolled_back_changes_never_emit_webhooks(acme, monkeypatch):
    """Events fire on commit: if the surrounding transaction rolls back, subscribers hear nothing."""
    from django.db import transaction

    from apps.webhooks.events import emit

    acme.clients[Role.ADMIN].post(acme.url("webhooks/"), {"url": "https://example.com/h", "events": ["*"]}, format="json")
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp())
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            emit(acme.ws, "issue.created", {"x": 1})
            raise RuntimeError("rollback")
    assert WebhookDelivery.objects.count() == 0
    with transaction.atomic():
        emit(acme.ws, "issue.created", {"x": 1})
    assert WebhookDelivery.objects.count() == 1
