"""Cross-tenant leak tests: a user in workspace A must never see, change or delete
anything in workspace B, through any endpoint, however IDs are supplied."""
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.audit.models import AuditLog
from apps.projects.models import Attachment, Comment, Issue, Label, Project, Sprint
from apps.workspaces.models import Role

from .conftest import make_user, client_for

LIST_ENDPOINTS = [
    "projects/", "issues/", "sprints/", "labels/", "statuses/", "transitions/", "columns/", "comments/",
    "attachments/", "saved-filters/", "members/", "invitations/", "audit-log/", "webhooks/",
    "webhook-deliveries/", "notifications/", "dashboard/", "billing/", "reports/weekly/", "search/?q=ab",
]


@pytest.mark.django_db
class TestWorkspaceAccess:
    def test_outsider_gets_404_not_403_for_every_endpoint(self, acme, globex):
        """404 (not 403) so we never confirm that another tenant's workspace exists."""
        outsider = globex.clients[Role.OWNER]
        for ep in LIST_ENDPOINTS:
            r = outsider.get(acme.url(ep))
            assert r.status_code == 404, f"{ep} -> {r.status_code}"

    def test_unknown_workspace_looks_identical_to_foreign_workspace(self, acme, globex):
        c = globex.clients[Role.OWNER]
        assert c.get("/api/w/does-not-exist/projects/").status_code == c.get(acme.url("projects/")).status_code == 404

    def test_anonymous_is_rejected(self, acme):
        from rest_framework.test import APIClient

        assert APIClient().get(acme.url("projects/")).status_code == 401

    def test_my_workspaces_lists_only_mine(self, acme, globex):
        r = acme.clients[Role.OWNER].get("/api/workspaces/")
        assert [w["slug"] for w in r.data] == [acme.ws.slug]


@pytest.mark.django_db
class TestDataLeaks:
    def test_lists_never_include_other_tenants_rows(self, acme, globex):
        acme.make_issue("acme secret")
        globex.make_issue("globex secret")
        r = acme.clients[Role.OWNER].get(acme.url("issues/"))
        titles = [i["title"] for i in r.data["results"]]
        assert titles == ["acme secret"]
        r = acme.clients[Role.OWNER].get(acme.url("projects/"))
        assert [p["key"] for p in r.data["results"]] == ["WEB"]

    def test_cannot_read_update_delete_foreign_issue_via_own_workspace_url(self, acme, globex):
        foreign = globex.make_issue("globex secret")
        c = acme.clients[Role.OWNER]
        assert c.get(acme.url(f"issues/{foreign.id}/")).status_code == 404
        assert c.patch(acme.url(f"issues/{foreign.id}/"), {"title": "pwned"}, format="json").status_code == 404
        assert c.delete(acme.url(f"issues/{foreign.id}/")).status_code == 404
        foreign.refresh_from_db()
        assert foreign.title == "globex secret"

    def test_cannot_use_foreign_ids_in_request_bodies(self, acme, globex):
        """Guessing another tenant's project/sprint/user/label IDs must be rejected on write."""
        c = acme.clients[Role.MEMBER]
        g_issue = globex.make_issue("g")
        g_sprint = Sprint.objects.create(workspace=globex.ws, project=globex.project, name="S1")
        g_label = Label.objects.create(workspace=globex.ws, name="secret")

        r = c.post(acme.url("issues/"), {"project": globex.project.id, "title": "x"}, format="json")
        assert r.status_code == 400
        r = c.post(acme.url("issues/"), {"project": acme.project.id, "title": "x", "sprint": g_sprint.id}, format="json")
        assert r.status_code == 400
        r = c.post(acme.url("issues/"), {"project": acme.project.id, "title": "x", "labels": [g_label.id]}, format="json")
        assert r.status_code == 400
        r = c.post(acme.url("issues/"), {"project": acme.project.id, "title": "x", "parent": g_issue.id}, format="json")
        assert r.status_code == 400
        # assignee must be a member of THIS workspace
        r = c.post(acme.url("issues/"), {"project": acme.project.id, "title": "x",
                                         "assignee": globex.users[Role.MEMBER].id}, format="json")
        assert r.status_code == 400
        assert not Issue.objects.filter(workspace=acme.ws, title="x").exists()

    def test_cannot_comment_or_attach_on_foreign_issue(self, acme, globex):
        g_issue = globex.make_issue("g")
        c = acme.clients[Role.MEMBER]
        r = c.post(acme.url("comments/"), {"issue": g_issue.id, "body": "hi"}, format="json")
        assert r.status_code == 400
        f = SimpleUploadedFile("a.txt", b"hello")
        r = c.post(acme.url("attachments/"), {"issue": g_issue.id, "file": f}, format="multipart")
        assert r.status_code == 400
        assert Comment.objects.filter(issue=g_issue).count() == 0

    def test_move_with_foreign_neighbour_or_status_rejected(self, acme, globex):
        mine = acme.make_issue("mine")
        theirs = globex.make_issue("theirs")
        c = acme.clients[Role.MEMBER]
        r = c.post(acme.url(f"issues/{mine.id}/move/"), {"status": acme.status("Done").id, "above": theirs.id}, format="json")
        assert r.status_code == 404
        r = c.post(acme.url(f"issues/{mine.id}/move/"), {"status": globex.status("Done", globex.project).id}, format="json")
        assert r.status_code == 404

    def test_attachment_download_is_membership_checked(self, acme, globex):
        issue = acme.make_issue("with file")
        f = SimpleUploadedFile("note.txt", b"top secret")
        r = acme.clients[Role.MEMBER].post(acme.url("attachments/"), {"issue": issue.id, "file": f}, format="multipart")
        assert r.status_code == 201
        att = Attachment.objects.get()
        assert acme.clients[Role.VIEWER].get(acme.url(f"attachments/{att.id}/download/")).status_code == 200
        assert globex.clients[Role.OWNER].get(acme.url(f"attachments/{att.id}/download/")).status_code == 404
        assert globex.clients[Role.OWNER].get(globex.url(f"attachments/{att.id}/download/")).status_code == 404

    def test_audit_log_is_tenant_scoped(self, acme, globex):
        acme.make_issue("a")
        globex.make_issue("g")
        r = acme.clients[Role.ADMIN].get(acme.url("audit-log/"))
        assert r.status_code == 200
        assert all(AuditLog.objects.get(pk=x["id"]).workspace_id == acme.ws.id for x in r.data["results"])
        assert not any("globex" in x["object_repr"].lower() for x in r.data["results"])

    def test_dashboard_and_search_do_not_leak(self, acme, globex):
        acme.make_issue("shared-term acme")
        globex.make_issue("shared-term globex")
        r = acme.clients[Role.VIEWER].get(acme.url("search/?q=shared-term"))
        assert [i["title"] for i in r.data["issues"]] == ["shared-term acme"]
        r = acme.clients[Role.VIEWER].get(acme.url("dashboard/"))
        assert r.data["totals"]["issues"] == 1

    def test_user_in_both_workspaces_sees_each_separately(self, acme, globex):
        from apps.workspaces.models import Membership

        both = make_user("both@example.com")
        Membership.objects.create(user=both, workspace=acme.ws, role=Role.MEMBER)
        Membership.objects.create(user=both, workspace=globex.ws, role=Role.VIEWER)
        acme.make_issue("a1"); globex.make_issue("g1")
        c = client_for(both)
        assert [i["title"] for i in c.get(acme.url("issues/")).data["results"]] == ["a1"]
        assert [i["title"] for i in c.get(globex.url("issues/")).data["results"]] == ["g1"]
        # role is per workspace: member in acme, viewer in globex
        assert c.post(acme.url("issues/"), {"project": acme.project.id, "title": "ok"}, format="json").status_code == 201
        assert c.post(globex.url("issues/"), {"project": globex.project.id, "title": "no"}, format="json").status_code == 403

    def test_deleting_workspace_removes_only_its_data(self, acme, globex):
        acme.make_issue("a"); globex.make_issue("g")
        assert acme.clients[Role.OWNER].delete(acme.url("")).status_code == 204
        assert Issue.objects.filter(workspace=globex.ws).count() == 1
        assert Issue.objects.filter(workspace=acme.ws).count() == 0
