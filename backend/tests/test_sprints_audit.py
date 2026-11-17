import datetime

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.projects.models import Issue, Sprint
from apps.workspaces.models import Role


def mk_sprint(acme, name="Sprint 1", **kw):
    r = acme.clients[Role.ADMIN].post(acme.url("sprints/"), {"project": acme.project.id, "name": name, **kw}, format="json")
    assert r.status_code == 201, r.data
    return Sprint.objects.get(pk=r.data["id"])


@pytest.mark.django_db
class TestSprints:
    def test_lifecycle_start_and_close_moves_unfinished_to_backlog(self, acme):
        s = mk_sprint(acme)
        a = acme.make_issue("done one", story_points=5, sprint=s.id)
        b = acme.make_issue("open one", story_points=3, sprint=s.id)
        admin = acme.clients[Role.ADMIN]
        r = admin.post(acme.url(f"sprints/{s.id}/start/"))
        assert r.status_code == 200 and r.data["state"] == "active" and r.data["committed_points"] == 8
        acme.clients[Role.MEMBER].post(acme.url(f"issues/{a.id}/move/"), {"status": acme.status("Done").id}, format="json")
        r = admin.post(acme.url(f"sprints/{s.id}/close/"))
        assert r.status_code == 200 and r.data["state"] == "closed" and r.data["completed_points"] == 5
        a.refresh_from_db(); b.refresh_from_db()
        assert a.sprint_id == s.id and b.sprint_id is None

    def test_close_can_carry_over_to_next_sprint(self, acme):
        s1, s2 = mk_sprint(acme, "S1"), mk_sprint(acme, "S2")
        b = acme.make_issue("open", sprint=s1.id)
        admin = acme.clients[Role.ADMIN]
        admin.post(acme.url(f"sprints/{s1.id}/start/"))
        admin.post(acme.url(f"sprints/{s1.id}/close/"), {"move_open_to": s2.id}, format="json")
        b.refresh_from_db()
        assert b.sprint_id == s2.id

    def test_only_one_active_sprint_and_must_have_issues(self, acme):
        s1, s2 = mk_sprint(acme, "S1"), mk_sprint(acme, "S2")
        admin = acme.clients[Role.ADMIN]
        assert admin.post(acme.url(f"sprints/{s1.id}/start/")).status_code == 400  # empty
        acme.make_issue("a", sprint=s1.id); acme.make_issue("b", sprint=s2.id)
        assert admin.post(acme.url(f"sprints/{s1.id}/start/")).status_code == 200
        r = admin.post(acme.url(f"sprints/{s2.id}/start/"))
        assert r.status_code == 409 and r.data["code"] == "active_sprint_exists"

    def test_cannot_add_to_closed_sprint_or_delete_active(self, acme):
        s = mk_sprint(acme)
        acme.make_issue("a", sprint=s.id)
        admin = acme.clients[Role.ADMIN]
        admin.post(acme.url(f"sprints/{s.id}/start/"))
        assert admin.delete(acme.url(f"sprints/{s.id}/")).status_code == 400
        admin.post(acme.url(f"sprints/{s.id}/close/"))
        r = acme.clients[Role.MEMBER].post(acme.url("issues/"), {"project": acme.project.id, "title": "late", "sprint": s.id}, format="json")
        assert r.status_code == 400

    def test_date_validation(self, acme):
        r = acme.clients[Role.ADMIN].post(acme.url("sprints/"), {"project": acme.project.id, "name": "x",
                                          "start_date": "2026-11-10", "end_date": "2026-11-01"}, format="json")
        assert r.status_code == 400

    def test_burndown_series(self, acme):
        s = mk_sprint(acme, start_date=str(timezone.localdate() - datetime.timedelta(days=2)),
                      end_date=str(timezone.localdate() + datetime.timedelta(days=2)))
        a = acme.make_issue("a", story_points=5, sprint=s.id); acme.make_issue("b", story_points=5, sprint=s.id)
        admin = acme.clients[Role.ADMIN]
        admin.post(acme.url(f"sprints/{s.id}/start/"))
        acme.clients[Role.MEMBER].post(acme.url(f"issues/{a.id}/move/"), {"status": acme.status("Done").id}, format="json")
        d = admin.get(acme.url(f"sprints/{s.id}/burndown/")).data
        assert d["total_points"] == 10 and len(d["days"]) == 5
        assert d["days"][0]["ideal"] == 10 and d["days"][-1]["ideal"] == 0
        today = timezone.localdate().isoformat()
        assert next(x for x in d["days"] if x["date"] == today)["remaining"] == 5
        assert d["days"][-1]["remaining"] is None  # future days are not plotted

    def test_dashboard_numbers(self, acme):
        acme.make_issue("a", story_points=3); acme.make_issue("b", status=acme.status("Done").id)
        d = acme.clients[Role.VIEWER].get(acme.url("dashboard/")).data
        assert d["totals"]["issues"] == 2 and d["totals"]["done"] == 1 and d["totals"]["open"] == 1
        assert {x["name"] for x in d["by_status"]} >= {"To Do", "Done"}
        assert len(d["flow"]) == 14


@pytest.mark.django_db
class TestAudit:
    def test_create_update_delete_are_logged_with_actor_and_diff(self, acme):
        issue = acme.make_issue("original", as_role=Role.MEMBER)
        acme.clients[Role.ADMIN].patch(acme.url(f"issues/{issue.id}/"), {"title": "renamed", "priority": "high"}, format="json")
        acme.clients[Role.ADMIN].delete(acme.url(f"issues/{issue.id}/"))
        logs = list(AuditLog.objects.filter(workspace=acme.ws, model="Issue", object_id=str(issue.id)).order_by("id"))
        assert [l.action for l in logs] == ["create", "update", "delete"]
        assert logs[0].actor == acme.users[Role.MEMBER]
        assert logs[1].actor == acme.users[Role.ADMIN]
        assert logs[1].changes["title"] == {"old": "original", "new": "renamed"}
        assert logs[1].changes["priority"]["new"] == "high"

    def test_status_change_is_human_readable(self, acme):
        issue = acme.make_issue("x")
        acme.clients[Role.MEMBER].post(acme.url(f"issues/{issue.id}/move/"), {"status": acme.status("Done").id}, format="json")
        log = AuditLog.objects.filter(model="Issue", object_id=str(issue.id), action="update").latest("id")
        assert log.changes["status"] == {"old": "To Do", "new": "Done"}
        assert "rank" not in log.changes and "updated_at" not in log.changes

    def test_noop_update_writes_nothing(self, acme):
        issue = acme.make_issue("x")
        n = AuditLog.objects.count()
        acme.clients[Role.MEMBER].patch(acme.url(f"issues/{issue.id}/"), {"title": "x"}, format="json")
        assert AuditLog.objects.count() == n

    def test_api_exposes_filters_and_is_read_only(self, acme):
        issue = acme.make_issue("x")
        a = acme.clients[Role.ADMIN]
        r = a.get(acme.url(f"audit-log/?model=Issue&object_id={issue.id}"))
        assert r.status_code == 200 and r.data["count"] >= 1
        assert a.post(acme.url("audit-log/"), {}, format="json").status_code == 405
        h = acme.clients[Role.VIEWER].get(acme.url(f"issues/{issue.id}/history/"))
        assert h.status_code == 200 and h.data[0]["action"] == "create"

    def test_membership_and_label_changes_are_logged(self, acme):
        acme.clients[Role.MEMBER].post(acme.url("labels/"), {"name": "ops"}, format="json")
        from apps.workspaces.models import Membership

        mid = Membership.objects.get(user=acme.users[Role.MEMBER], workspace=acme.ws).id
        acme.clients[Role.OWNER].patch(acme.url(f"members/{mid}/"), {"role": "admin"}, format="json")
        assert AuditLog.objects.filter(model="Label", action="create").exists()
        assert AuditLog.objects.filter(model="Membership", action="update", changes__role__new="admin").exists()
