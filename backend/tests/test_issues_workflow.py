import pytest

from apps.projects.models import Issue, WorkflowTransition
from apps.workspaces.models import Role


@pytest.mark.django_db
class TestIssues:
    def test_numbering_is_sequential_per_project(self, acme):
        a, b, c = (acme.make_issue(f"i{n}") for n in range(3))
        assert [a.key, b.key, c.key] == ["WEB-1", "WEB-2", "WEB-3"]
        other = acme.clients[Role.OWNER].post(acme.url("projects/"), {"key": "API", "name": "Api"}, format="json").data["id"]
        from apps.projects.models import Project

        d = acme.make_issue("other", project=Project.objects.get(pk=other))
        assert d.key == "API-1"

    def test_defaults_first_status_reporter_and_rank(self, acme):
        i = acme.make_issue("x")
        assert i.status.name == "To Do" and i.reporter == acme.users[Role.MEMBER]
        j = acme.make_issue("y")
        assert j.rank > i.rank

    def test_validation(self, acme):
        c = acme.clients[Role.MEMBER]
        assert c.post(acme.url("issues/"), {"project": acme.project.id, "title": "  "}, format="json").status_code == 400
        assert c.post(acme.url("issues/"), {"project": acme.project.id, "title": "t", "story_points": 500}, format="json").status_code == 400
        assert c.post(acme.url("issues/"), {"project": acme.project.id, "title": "t", "type": "nonsense"}, format="json").status_code == 400

    def test_project_key_rules(self, acme):
        c = acme.clients[Role.ADMIN]
        assert c.post(acme.url("projects/"), {"key": "web", "name": "dup"}, format="json").status_code == 400  # WEB exists (case-insens.)
        assert c.post(acme.url("projects/"), {"key": "1AB", "name": "x"}, format="json").status_code == 400
        assert c.patch(acme.url(f"projects/{acme.project.id}/"), {"key": "NEW"}, format="json").status_code == 400

    def test_filters_and_search(self, acme):
        me = acme.users[Role.MEMBER]
        acme.make_issue("Login bug", type="bug", priority="high", assignee=me.id)
        acme.make_issue("Write docs", type="task")
        c = acme.clients[Role.VIEWER]
        get = lambda q: [i["title"] for i in c.get(acme.url(f"issues/?{q}")).data["results"]]
        assert get("type=bug") == ["Login bug"]
        assert get("assignee=none") == ["Write docs"]
        assert get(f"assignee={me.id}") == ["Login bug"]
        assert get("q=docs") == ["Write docs"]
        assert get("q=WEB-1") == ["Login bug"]
        assert get("priority=high") == ["Login bug"]
        assert get("backlog=true") == ["Login bug", "Write docs"] or set(get("backlog=true")) == {"Login bug", "Write docs"}

    def test_resolved_at_set_when_done(self, acme):
        i = acme.make_issue("x")
        acme.clients[Role.MEMBER].patch(acme.url(f"issues/{i.id}/"), {"status": acme.status("Done").id}, format="json")
        i.refresh_from_db()
        assert i.resolved_at is not None
        acme.clients[Role.MEMBER].patch(acme.url(f"issues/{i.id}/"), {"status": acme.status("To Do").id}, format="json")
        i.refresh_from_db()
        assert i.resolved_at is None

    def test_labels_and_parent(self, acme):
        c = acme.clients[Role.MEMBER]
        lab = c.post(acme.url("labels/"), {"name": "frontend"}, format="json").data["id"]
        epic = acme.make_issue("Epic", type="epic")
        r = c.post(acme.url("issues/"), {"project": acme.project.id, "title": "child", "labels": [lab], "parent": epic.id}, format="json")
        assert r.status_code == 201 and r.data["label_details"][0]["name"] == "frontend" and r.data["parent"] == epic.id
        assert c.patch(acme.url(f"issues/{epic.id}/"), {"parent": epic.id}, format="json").status_code == 400

    def test_comments_and_mentions(self, acme):
        issue = acme.make_issue("x")
        handle = acme.users[Role.ADMIN].email.split("@")[0]
        r = acme.clients[Role.MEMBER].post(acme.url("comments/"), {"issue": issue.id, "body": f"ping @{handle} and @nobody"}, format="json")
        assert r.status_code == 201 and r.data["mention_ids"] == [acme.users[Role.ADMIN].id]
        assert acme.clients[Role.MEMBER].post(acme.url("comments/"), {"issue": issue.id, "body": " "}, format="json").status_code == 400


@pytest.mark.django_db
class TestCustomWorkflow:
    def test_open_workflow_allows_any_move(self, acme):
        i = acme.make_issue("x")
        r = acme.clients[Role.MEMBER].patch(acme.url(f"issues/{i.id}/"), {"status": acme.status("Done").id}, format="json")
        assert r.status_code == 200

    def test_transitions_are_enforced_on_patch_and_move(self, acme):
        todo, prog, review, done = (acme.status(n) for n in ["To Do", "In Progress", "In Review", "Done"])
        WorkflowTransition.objects.create(workspace=acme.ws, project=acme.project, from_status=todo, to_status=prog)
        WorkflowTransition.objects.create(workspace=acme.ws, project=acme.project, from_status=prog, to_status=review)
        WorkflowTransition.objects.create(workspace=acme.ws, project=acme.project, from_status=review, to_status=done)
        i = acme.make_issue("x")
        m = acme.clients[Role.MEMBER]
        r = m.patch(acme.url(f"issues/{i.id}/"), {"status": done.id}, format="json")
        assert r.status_code == 400 and "does not allow" in str(r.data)
        assert m.post(acme.url(f"issues/{i.id}/move/"), {"status": done.id}, format="json").status_code == 400
        assert m.post(acme.url(f"issues/{i.id}/move/"), {"status": prog.id}, format="json").status_code == 200
        t = m.get(acme.url(f"issues/{i.id}/transitions/")).data
        assert [s["name"] for s in t] == ["In Review"]

    def test_linear_preset_and_reset(self, acme):
        a = acme.clients[Role.ADMIN]
        assert a.post(acme.url("transitions/linear/"), {"project": acme.project.id}, format="json").status_code == 200
        i = acme.make_issue("x")
        assert acme.clients[Role.MEMBER].patch(acme.url(f"issues/{i.id}/"), {"status": acme.status("Done").id}, format="json").status_code == 400
        assert a.post(acme.url("transitions/reset/"), {"project": acme.project.id}, format="json").status_code == 200
        assert acme.clients[Role.MEMBER].patch(acme.url(f"issues/{i.id}/"), {"status": acme.status("Done").id}, format="json").status_code == 200

    def test_custom_status_appears_on_board_and_cannot_be_deleted_with_issues(self, acme):
        a = acme.clients[Role.ADMIN]
        r = a.post(acme.url("statuses/"), {"project": acme.project.id, "name": "QA", "category": "in_progress", "order": 9}, format="json")
        assert r.status_code == 201
        board = a.get(acme.url(f"projects/{acme.project.id}/board/")).data
        assert "QA" in [c["status"]["name"] for c in board["columns"]]
        i = acme.make_issue("x", status=r.data["id"])
        assert a.delete(acme.url(f"statuses/{r.data['id']}/")).status_code == 400
        i.delete()
        assert a.delete(acme.url(f"statuses/{r.data['id']}/")).status_code == 204


@pytest.mark.django_db
class TestKanbanMove:
    def _order(self, acme, status_name):
        board = acme.clients[Role.VIEWER].get(acme.url(f"projects/{acme.project.id}/board/")).data
        col = next(c for c in board["columns"] if c["status"]["name"] == status_name)
        return [i["title"] for i in col["issues"]]

    def test_board_groups_issues_by_column(self, acme):
        acme.make_issue("a"); acme.make_issue("b", status=acme.status("Done").id)
        assert self._order(acme, "To Do") == ["a"] and self._order(acme, "Done") == ["b"]

    def test_reorder_within_and_across_columns_touches_one_row(self, acme):
        a, b, c = (acme.make_issue(n) for n in "abc")
        m = acme.clients[Role.MEMBER]
        before = dict(Issue.objects.values_list("id", "rank"))
        # drop c between a and b
        r = m.post(acme.url(f"issues/{c.id}/move/"), {"status": c.status_id, "above": a.id, "below": b.id}, format="json")
        assert r.status_code == 200
        assert self._order(acme, "To Do") == ["a", "c", "b"]
        after = dict(Issue.objects.values_list("id", "rank"))
        assert [k for k in before if before[k] != after[k]] == [c.id]
        # to the top, and to the bottom
        m.post(acme.url(f"issues/{b.id}/move/"), {"status": b.status_id, "below": a.id}, format="json")
        assert self._order(acme, "To Do") == ["b", "a", "c"]
        m.post(acme.url(f"issues/{b.id}/move/"), {"status": b.status_id, "above": c.id}, format="json")
        assert self._order(acme, "To Do") == ["a", "c", "b"]
        # across columns
        done = acme.status("Done")
        m.post(acme.url(f"issues/{a.id}/move/"), {"status": done.id}, format="json")
        assert self._order(acme, "Done") == ["a"] and self._order(acme, "To Do") == ["c", "b"]
        a.refresh_from_db()
        assert a.resolved_at is not None

    def test_rank_rebalances_when_gap_collapses(self, acme):
        a, b = acme.make_issue("a"), acme.make_issue("b")
        Issue.objects.filter(pk=b.pk).update(rank=a.rank + 1e-9)
        c = acme.make_issue("c")
        r = acme.clients[Role.MEMBER].post(acme.url(f"issues/{c.id}/move/"), {"status": c.status_id, "above": a.id, "below": b.id}, format="json")
        assert r.status_code == 200
        assert self._order(acme, "To Do") == ["a", "c", "b"]

    def test_neighbour_must_be_in_target_column(self, acme):
        a = acme.make_issue("a"); b = acme.make_issue("b", status=acme.status("Done").id)
        r = acme.clients[Role.MEMBER].post(acme.url(f"issues/{a.id}/move/"), {"status": a.status_id, "above": b.id}, format="json")
        assert r.status_code == 400

    def test_wip_limit_blocks_move_in(self, acme):
        prog = acme.status("In Progress")
        col = acme.project.boards.first().columns.get(status=prog)
        assert acme.clients[Role.ADMIN].patch(acme.url(f"columns/{col.id}/"), {"wip_limit": 1}, format="json").status_code == 200
        a, b = acme.make_issue("a"), acme.make_issue("b")
        m = acme.clients[Role.MEMBER]
        assert m.post(acme.url(f"issues/{a.id}/move/"), {"status": prog.id}, format="json").status_code == 200
        r = m.post(acme.url(f"issues/{b.id}/move/"), {"status": prog.id}, format="json")
        assert r.status_code == 409 and r.data["code"] == "wip_limit"
        # reordering inside the full column is still fine
        assert m.post(acme.url(f"issues/{a.id}/move/"), {"status": prog.id}, format="json").status_code == 200

    def test_board_filters(self, acme):
        me = acme.users[Role.MEMBER]
        acme.make_issue("mine", assignee=me.id); acme.make_issue("other")
        r = acme.clients[Role.MEMBER].get(acme.url(f"projects/{acme.project.id}/board/?assignee=me")).data
        assert [i["title"] for c in r["columns"] for i in c["issues"]] == ["mine"]
