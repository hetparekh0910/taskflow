"""Role matrix: viewer < member < admin < owner."""
import pytest

from apps.workspaces.models import Invitation, Membership, Role

from .conftest import make_user


@pytest.mark.django_db
class TestRoleMatrix:
    def test_viewer_can_read_but_not_write(self, acme):
        issue = acme.make_issue("x")
        v = acme.clients[Role.VIEWER]
        assert v.get(acme.url("issues/")).status_code == 200
        assert v.get(acme.url("projects/")).status_code == 200
        assert v.post(acme.url("issues/"), {"project": acme.project.id, "title": "n"}, format="json").status_code == 403
        assert v.patch(acme.url(f"issues/{issue.id}/"), {"title": "n"}, format="json").status_code == 403
        assert v.post(acme.url("comments/"), {"issue": issue.id, "body": "hi"}, format="json").status_code == 403
        assert v.post(acme.url(f"issues/{issue.id}/move/"), {"status": acme.status("Done").id}, format="json").status_code == 403

    def test_member_works_on_issues_but_not_structure(self, acme):
        m = acme.clients[Role.MEMBER]
        issue = acme.make_issue("x")
        assert m.patch(acme.url(f"issues/{issue.id}/"), {"title": "renamed"}, format="json").status_code == 200
        assert m.post(acme.url("comments/"), {"issue": issue.id, "body": "hi"}, format="json").status_code == 201
        assert m.post(acme.url("labels/"), {"name": "bug"}, format="json").status_code == 201
        # structure + destructive actions need admin
        assert m.delete(acme.url(f"issues/{issue.id}/")).status_code == 403
        assert m.post(acme.url("projects/"), {"key": "NEW", "name": "New"}, format="json").status_code == 403
        assert m.post(acme.url("sprints/"), {"project": acme.project.id, "name": "S"}, format="json").status_code == 403
        assert m.post(acme.url("statuses/"), {"project": acme.project.id, "name": "QA"}, format="json").status_code == 403
        assert m.get(acme.url("audit-log/")).status_code == 403
        assert m.get(acme.url("webhooks/")).status_code == 403
        assert m.get(acme.url("invitations/")).status_code == 403

    def test_admin_manages_projects_sprints_audit_invites(self, acme):
        a = acme.clients[Role.ADMIN]
        assert a.post(acme.url("projects/"), {"key": "NEW", "name": "New"}, format="json").status_code == 201
        assert a.post(acme.url("sprints/"), {"project": acme.project.id, "name": "S"}, format="json").status_code == 201
        assert a.get(acme.url("audit-log/")).status_code == 200
        assert a.post(acme.url("invitations/"), {"email": "new@x.com", "role": "member"}, format="json").status_code == 201
        issue = acme.make_issue("x")
        assert a.delete(acme.url(f"issues/{issue.id}/")).status_code == 204

    def test_billing_is_owner_only_for_changes(self, acme):
        for role in (Role.ADMIN, Role.MEMBER, Role.VIEWER):
            assert acme.clients[role].post(acme.url("billing/checkout/"), {"plan": "pro"}, format="json").status_code == 403
        assert acme.clients[Role.OWNER].post(acme.url("billing/checkout/"), {"plan": "pro"}, format="json").status_code == 200
        # but everyone can see usage
        assert acme.clients[Role.VIEWER].get(acme.url("billing/")).status_code == 200

    def test_only_owner_deletes_workspace_or_changes_ownership(self, acme):
        assert acme.clients[Role.ADMIN].delete(acme.url("")).status_code == 403
        mid = Membership.objects.get(user=acme.users[Role.MEMBER], workspace=acme.ws).id
        # admin cannot promote to owner
        r = acme.clients[Role.ADMIN].patch(acme.url(f"members/{mid}/"), {"role": "owner"}, format="json")
        assert r.status_code == 403
        r = acme.clients[Role.OWNER].patch(acme.url(f"members/{mid}/"), {"role": "admin"}, format="json")
        assert r.status_code == 200

    def test_last_owner_cannot_leave_or_be_demoted(self, acme):
        mid = Membership.objects.get(user=acme.owner, workspace=acme.ws).id
        assert acme.clients[Role.OWNER].delete(acme.url(f"members/{mid}/")).status_code == 400
        assert acme.clients[Role.OWNER].patch(acme.url(f"members/{mid}/"), {"role": "member"}, format="json").status_code == 400

    def test_member_can_leave_but_not_remove_others(self, acme):
        me = Membership.objects.get(user=acme.users[Role.MEMBER], workspace=acme.ws).id
        other = Membership.objects.get(user=acme.users[Role.VIEWER], workspace=acme.ws).id
        c = acme.clients[Role.MEMBER]
        assert c.delete(acme.url(f"members/{other}/")).status_code == 403
        assert c.delete(acme.url(f"members/{me}/")).status_code == 204

    def test_comment_edit_only_by_author_or_admin(self, acme):
        issue = acme.make_issue("x")
        r = acme.clients[Role.MEMBER].post(acme.url("comments/"), {"issue": issue.id, "body": "mine"}, format="json")
        cid = r.data["id"]
        other_member = make_user("m2@example.com")
        Membership.objects.create(user=other_member, workspace=acme.ws, role=Role.MEMBER)
        from .conftest import client_for

        other = client_for(other_member)
        assert other.patch(acme.url(f"comments/{cid}/"), {"body": "hax"}, format="json").status_code == 403
        assert acme.clients[Role.ADMIN].patch(acme.url(f"comments/{cid}/"), {"body": "moderated"}, format="json").status_code == 200


@pytest.mark.django_db
class TestInvitations:
    def test_invite_and_signup_flow(self, acme):
        from rest_framework.test import APIClient

        acme.clients[Role.ADMIN].post(acme.url("invitations/"), {"email": "Newbie@Example.com", "role": "member"}, format="json")
        inv = Invitation.objects.get()
        assert inv.email == "newbie@example.com"
        anon = APIClient()
        assert anon.get(f"/api/invitations/{inv.token}/").data["workspace_name"] == "Acme"
        r = anon.post("/api/auth/register/", {"email": "newbie@example.com", "password": "pass12345",
                                              "invite_token": inv.token}, format="json")
        assert r.status_code == 201 and r.data["workspace"]["slug"] == acme.ws.slug
        assert r.data["workspace"]["role"] == "member"
        # token is single-use
        assert anon.post("/api/auth/register/", {"email": "newbie@example.com", "password": "pass12345",
                                                 "invite_token": inv.token}, format="json").status_code == 400

    def test_invite_token_bound_to_email(self, acme):
        from rest_framework.test import APIClient

        acme.clients[Role.ADMIN].post(acme.url("invitations/"), {"email": "a@x.com", "role": "member"}, format="json")
        inv = Invitation.objects.get()
        r = APIClient().post("/api/auth/register/", {"email": "someone-else@x.com", "password": "pass12345",
                                                     "invite_token": inv.token}, format="json")
        assert r.status_code == 400

    def test_cannot_invite_as_owner_or_duplicate(self, acme):
        a = acme.clients[Role.ADMIN]
        assert a.post(acme.url("invitations/"), {"email": "o@x.com", "role": "owner"}, format="json").status_code == 400
        assert a.post(acme.url("invitations/"), {"email": "d@x.com", "role": "member"}, format="json").status_code == 201
        assert a.post(acme.url("invitations/"), {"email": "d@x.com", "role": "member"}, format="json").status_code == 400
        assert a.post(acme.url("invitations/"), {"email": acme.owner.email, "role": "member"}, format="json").status_code == 400


@pytest.mark.django_db
class TestAuth:
    def test_register_login_me(self):
        from rest_framework.test import APIClient

        c = APIClient()
        r = c.post("/api/auth/register/", {"email": "a@b.com", "password": "longenough1", "workspace_name": "Foo Inc"}, format="json")
        assert r.status_code == 201 and r.data["workspace"]["slug"] == "foo-inc" and r.data["workspace"]["role"] == "owner"
        r = c.post("/api/auth/login/", {"email": "a@b.com", "password": "longenough1"}, format="json")
        assert r.status_code == 200 and "access" in r.data
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
        assert c.get("/api/auth/me/").data["email"] == "a@b.com"

    def test_weak_password_and_duplicate_email_rejected(self):
        from rest_framework.test import APIClient

        c = APIClient()
        assert c.post("/api/auth/register/", {"email": "a@b.com", "password": "short"}, format="json").status_code == 400
        c.post("/api/auth/register/", {"email": "a@b.com", "password": "longenough1"}, format="json")
        assert c.post("/api/auth/register/", {"email": "A@B.com", "password": "longenough1"}, format="json").status_code == 400

    def test_workspace_slug_collision_gets_suffix(self):
        from rest_framework.test import APIClient

        c = APIClient()
        a = c.post("/api/auth/register/", {"email": "a@b.com", "password": "longenough1", "workspace_name": "Same"}, format="json")
        b = c.post("/api/auth/register/", {"email": "c@d.com", "password": "longenough1", "workspace_name": "Same"}, format="json")
        assert a.data["workspace"]["slug"] == "same" and b.data["workspace"]["slug"] == "same-2"
