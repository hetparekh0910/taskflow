import itertools

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.projects.models import Issue, Project
from apps.workspaces.models import Membership, Role
from apps.workspaces.services import create_workspace

_counter = itertools.count(1)


@pytest.fixture(autouse=True)
def _run_on_commit_immediately(request, monkeypatch):
    """pytest-django wraps each test in a transaction that never commits, so on_commit hooks
    would never fire. Run them inline, except in tests marked transaction=True, which use real commits."""
    marker = request.node.get_closest_marker("django_db")
    if marker and marker.kwargs.get("transaction"):
        return
    from django.db import transaction

    monkeypatch.setattr(transaction, "on_commit", lambda func, using=None, robust=False: func())


@pytest.fixture(autouse=True)
def _settings(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.STRIPE_SECRET_KEY = ""
    settings.WEBHOOK_ALLOW_PRIVATE = True
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


def make_user(email=None, name=""):
    n = next(_counter)
    return User.objects.create_user(email=email or f"user{n}@example.com", password="pass12345", full_name=name or f"User {n}")


def client_for(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


class Tenant:
    """A workspace with one user per role and a ready-to-use project."""

    def __init__(self, name="Acme", plan="business"):
        self.owner = make_user(f"owner-{name.lower()}@example.com", f"{name} Owner")
        self.ws = create_workspace(name, self.owner)
        self.ws.plan = plan
        self.ws.save(update_fields=["plan"])
        self.users = {Role.OWNER: self.owner}
        for role in (Role.ADMIN, Role.MEMBER, Role.VIEWER):
            u = make_user(f"{role}-{name.lower()}@example.com", f"{name} {role}")
            Membership.objects.create(user=u, workspace=self.ws, role=role)
            self.users[role] = u
        self.clients = {r: client_for(u) for r, u in self.users.items()}
        self.base = f"/api/w/{self.ws.slug}"
        self.project = None

    def url(self, path):
        return f"{self.base}/{path}"

    def make_project(self, key="WEB", name="Website"):
        r = self.clients[Role.OWNER].post(self.url("projects/"), {"key": key, "name": name}, format="json")
        assert r.status_code == 201, r.data
        self.project = Project.objects.get(pk=r.data["id"])
        return self.project

    def make_issue(self, title="Fix it", as_role=Role.MEMBER, **extra):
        project = extra.pop("project", self.project)
        r = self.clients[as_role].post(
            self.url("issues/"), {"project": project.id, "title": title, **extra}, format="json"
        )
        assert r.status_code == 201, r.data
        return Issue.objects.get(pk=r.data["id"])

    def status(self, name, project=None):
        return (project or self.project).statuses.get(name=name)


@pytest.fixture
def acme():
    t = Tenant("Acme")
    t.make_project()
    return t


@pytest.fixture
def globex():
    t = Tenant("Globex")
    t.make_project("OPS", "Operations")
    return t
