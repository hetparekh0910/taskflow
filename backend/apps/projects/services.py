import re
from collections import defaultdict
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from .models import RANK_STEP, BoardColumn, Issue, SprintState, StatusCategory, WorkflowTransition

User = get_user_model()
MENTION_RE = re.compile(r"(?<![\w.])@([A-Za-z0-9._+-]+)")


class Conflict(APIException):
    status_code = 409
    default_code = "conflict"


def check_transition(project, from_status, to_status):
    """Enforce the custom workflow. No transitions defined => open workflow."""
    qs = WorkflowTransition.objects.filter(project=project)
    if not qs.exists():
        return
    if not qs.filter(from_status=from_status, to_status=to_status).exists():
        raise ValidationError(
            {
                "status": f"Workflow does not allow moving from '{from_status.name}' to '{to_status.name}'.",
                "code": "invalid_transition",
            }
        )


def allowed_transitions(project, from_status):
    qs = WorkflowTransition.objects.filter(project=project)
    if not qs.exists():
        return list(project.statuses.exclude(pk=from_status.pk).values_list("id", flat=True))
    return list(qs.filter(from_status=from_status).values_list("to_status_id", flat=True))


def allowed_map(project, status_ids):
    """{status_id: [allowed target ids]} for every status in ONE query (the board needs it per column)."""
    pairs = list(WorkflowTransition.objects.filter(project=project).values_list("from_status_id", "to_status_id"))
    if not pairs:  # open workflow
        return {sid: [o for o in status_ids if o != sid] for sid in status_ids}
    out = {sid: [] for sid in status_ids}
    for a, b in pairs:
        out.setdefault(a, []).append(b)
    return out


def resolve_mentions(workspace, body):
    """@alice -> workspace members whose email local-part equals 'alice' (case-insensitive)."""
    handles = {h.lower() for h in MENTION_RE.findall(body or "")}
    if not handles:
        return []
    users = User.objects.filter(memberships__workspace=workspace)
    return [u for u in users if u.email.split("@")[0].lower() in handles]


@transaction.atomic
def move_issue(issue, target_status, above=None, below=None):
    """Drag-and-drop: place `issue` in `target_status` between `above` and `below`.

    Only the moved row is written (fractional ranking). If two neighbours get too
    close the column is rebalanced once, then the rank is recomputed.
    """
    project = issue.project
    for neighbour in (above, below):
        if neighbour is not None:
            if neighbour.project_id != project.id or neighbour.status_id != target_status.id:
                raise ValidationError({"detail": "Neighbour issues must be in the target column."})
            if neighbour.pk == issue.pk:
                raise ValidationError({"detail": "An issue cannot be its own neighbour."})

    changed_column = target_status.id != issue.status_id
    if changed_column:
        check_transition(project, issue.status, target_status)
        col = BoardColumn.objects.filter(board__project=project, status=target_status).first()
        if col and col.wip_limit is not None:
            count = Issue.objects.filter(project=project, status=target_status).count()
            if count >= col.wip_limit:
                raise Conflict(
                    {"detail": f"WIP limit of {col.wip_limit} reached for '{target_status.name}'.", "code": "wip_limit"}
                )

    def compute():
        a = Issue.objects.get(pk=above.pk).rank if above else None
        b = Issue.objects.get(pk=below.pk).rank if below else None
        if a is not None and b is not None:
            if b - a < 1e-6:
                return None
            return (a + b) / 2
        if a is not None:
            return a + RANK_STEP
        if b is not None:
            return b - RANK_STEP
        return Issue.next_rank(project, target_status)

    rank = compute()
    if rank is None:
        Issue.rebalance(project, target_status)
        rank = compute()

    issue.status = target_status
    issue.rank = rank
    issue.resolved_at = timezone.now() if target_status.category == StatusCategory.DONE else None
    issue.save(update_fields=["status", "rank", "resolved_at", "updated_at"])
    return issue


# --------------------------------------------------------------------------- sprints


@transaction.atomic
def start_sprint(sprint):
    if sprint.state != SprintState.PLANNED:
        raise ValidationError("Only a planned sprint can be started.")
    if sprint.project.sprints.filter(state=SprintState.ACTIVE).exists():
        raise Conflict({"detail": "This project already has an active sprint.", "code": "active_sprint_exists"})
    if not sprint.issues.exists():
        raise ValidationError("Add at least one issue before starting the sprint.")
    today = timezone.localdate()
    sprint.state = SprintState.ACTIVE
    sprint.started_at = timezone.now()
    sprint.start_date = sprint.start_date or today
    sprint.end_date = sprint.end_date or (sprint.start_date + timedelta(days=14))
    sprint.committed_points = sprint.issues.aggregate(s=Sum("story_points"))["s"] or 0
    sprint.save()
    return sprint


@transaction.atomic
def close_sprint(sprint, move_open_to=None):
    """Close a sprint. Unfinished issues go to `move_open_to` (a planned sprint) or the backlog."""
    if sprint.state != SprintState.ACTIVE:
        raise ValidationError("Only an active sprint can be closed.")
    if move_open_to is not None:
        if move_open_to.project_id != sprint.project_id or move_open_to.state != SprintState.PLANNED:
            raise ValidationError("Target must be a planned sprint in the same project.")
    done = sprint.issues.filter(status__category=StatusCategory.DONE)
    sprint.completed_points = done.aggregate(s=Sum("story_points"))["s"] or 0
    sprint.issues.exclude(status__category=StatusCategory.DONE).update(sprint=move_open_to)
    sprint.state = SprintState.CLOSED
    sprint.closed_at = timezone.now()
    sprint.save()
    return sprint


def burndown(sprint):
    """Daily remaining-points series for a sprint plus the ideal line.

    Remaining(day) = committed points - points of issues resolved on or before that day.
    Scope added after start is included in `committed` for current sprint state.
    """
    start = sprint.start_date or (sprint.started_at.date() if sprint.started_at else None)
    end = sprint.end_date
    if not start or not end:
        return {"days": [], "total_points": 0}
    issues = list(sprint.issues.values("story_points", "resolved_at", "status__category"))
    total = sum(i["story_points"] or 0 for i in issues)
    if sprint.state == SprintState.CLOSED:
        total = sprint.committed_points or total
    days = (end - start).days + 1
    today = timezone.localdate()
    series = []
    for n in range(days):
        d = start + timedelta(days=n)
        ideal = round(total - total * n / max(days - 1, 1), 2)
        if d > today and sprint.state == SprintState.ACTIVE:
            remaining = None
        else:
            burned = sum(
                (i["story_points"] or 0)
                for i in issues
                if i["resolved_at"] and timezone.localtime(i["resolved_at"]).date() <= d
            )
            remaining = total - burned
        series.append({"date": d.isoformat(), "ideal": ideal, "remaining": remaining})
    return {"days": series, "total_points": total, "start": start.isoformat(), "end": end.isoformat()}


# --------------------------------------------------------------------------- dashboard


def dashboard(workspace, project=None):
    from .models import Sprint

    issues = Issue.objects.filter(workspace=workspace)
    if project is not None:
        issues = issues.filter(project=project)
    today = timezone.localdate()
    by_status = list(
        issues.values("status__name", "status__color", "status__category")
        .annotate(count=Count("id"))
        .order_by("status__category", "status__name")
    )
    # Merge same-named statuses across projects
    merged = defaultdict(lambda: {"count": 0, "color": "#94a3b8", "category": "todo"})
    for row in by_status:
        m = merged[row["status__name"]]
        m["count"] += row["count"]
        m["color"] = row["status__color"]
        m["category"] = row["status__category"]
    by_priority = list(issues.values("priority").annotate(count=Count("id")).order_by("priority"))
    by_type = list(issues.values("type").annotate(count=Count("id")))
    workload = list(
        issues.exclude(status__category=StatusCategory.DONE)
        .values("assignee__id", "assignee__full_name", "assignee__email")
        .annotate(open=Count("id"), points=Sum("story_points"))
        .order_by("-open")
    )
    overdue = issues.filter(due_date__lt=today).exclude(status__category=StatusCategory.DONE).count()
    week_ago = timezone.now() - timedelta(days=7)
    created_7d = issues.filter(created_at__gte=week_ago).count()
    resolved_7d = issues.filter(resolved_at__gte=week_ago).count()
    # created vs resolved per day, last 14 days: two grouped queries instead of 28
    start = today - timedelta(days=13)
    created_by_day = dict(
        issues.filter(created_at__date__gte=start).annotate(d=TruncDate("created_at")).values_list("d").annotate(n=Count("id"))
    )
    resolved_by_day = dict(
        issues.filter(resolved_at__date__gte=start).annotate(d=TruncDate("resolved_at")).values_list("d").annotate(n=Count("id"))
    )
    flow = []
    for n in range(13, -1, -1):
        d = today - timedelta(days=n)
        flow.append({"date": d.isoformat(), "created": created_by_day.get(d, 0), "resolved": resolved_by_day.get(d, 0)})
    sprints = Sprint.objects.filter(workspace=workspace, state=SprintState.CLOSED)
    if project is not None:
        sprints = sprints.filter(project=project)
    velocity = [
        {"sprint": s.name, "committed": s.committed_points, "completed": s.completed_points}
        for s in sprints.order_by("-closed_at")[:8]
    ][::-1]
    return {
        "totals": {
            "issues": issues.count(),
            "open": issues.exclude(status__category=StatusCategory.DONE).count(),
            "done": issues.filter(status__category=StatusCategory.DONE).count(),
            "overdue": overdue,
            "created_7d": created_7d,
            "resolved_7d": resolved_7d,
        },
        "by_status": [{"name": k, **v} for k, v in merged.items()],
        "by_priority": by_priority,
        "by_type": by_type,
        "workload": [
            {
                "user_id": w["assignee__id"],
                "name": (w["assignee__full_name"] or (w["assignee__email"] or "Unassigned").split("@")[0]),
                "open": w["open"],
                "points": w["points"] or 0,
            }
            for w in workload
        ],
        "flow": flow,
        "velocity": velocity,
    }
