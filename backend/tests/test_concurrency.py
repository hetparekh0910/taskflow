"""Issue keys (WEB-1, WEB-2...) must be unique and gap-free even when many people create issues at once.
Needs a database with real row locks, so it is skipped on SQLite and runs in CI against PostgreSQL."""
import threading

import pytest
from django.db import connection, connections

from apps.projects.models import Issue

from .conftest import Tenant

pytestmark = pytest.mark.skipif(connection.vendor != "postgresql", reason="needs PostgreSQL row locking")


@pytest.mark.django_db(transaction=True)
def test_concurrent_issue_creation_yields_unique_sequential_numbers():
    t = Tenant("Race")
    project = t.make_project("RACE", "Race")
    errors, per_thread, threads_n = [], 6, 8

    def worker():
        try:
            for i in range(per_thread):
                t.clients["member"].post(t.url("issues/"), {"project": project.id, "title": f"c{i}"}, format="json").data
        except Exception as e:  # pragma: no cover
            errors.append(repr(e))
        finally:
            connections.close_all()

    ts = [threading.Thread(target=worker) for _ in range(threads_n)]
    [x.start() for x in ts]
    [x.join() for x in ts]
    assert not errors, errors
    numbers = sorted(Issue.objects.filter(project=project).values_list("number", flat=True))
    assert numbers == list(range(1, threads_n * per_thread + 1))
