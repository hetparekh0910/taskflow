from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from .models import Notification


def notify(workspace, user, kind, message, issue=None, email=False):
    """Create an in-app notification (and optionally queue an email via Celery)."""
    if user is None:
        return None
    n = Notification.objects.create(workspace=workspace, user=user, kind=kind, message=message[:300], issue=issue)
    if email:
        from .tasks import send_notification_email

        transaction.on_commit(lambda: send_notification_email.delay(n.id))
    return n


def weekly_report(workspace, days=7):
    """Plain-data summary of the last `days` days, used by both the API and the weekly email."""
    from apps.projects.models import Issue, Project, Sprint, SprintState, StatusCategory

    since = timezone.now() - timedelta(days=days)
    issues = Issue.objects.filter(workspace=workspace)
    today = timezone.localdate()
    created = issues.filter(created_at__gte=since)
    resolved = issues.filter(resolved_at__gte=since)
    per_project = []
    for p in Project.objects.filter(workspace=workspace, archived=False):
        pi = issues.filter(project=p)
        per_project.append(
            {
                "key": p.key,
                "name": p.name,
                "open": pi.exclude(status__category=StatusCategory.DONE).count(),
                "created": pi.filter(created_at__gte=since).count(),
                "resolved": pi.filter(resolved_at__gte=since).count(),
            }
        )
    top = (
        resolved.exclude(assignee__isnull=True)
        .values("assignee__full_name", "assignee__email")
        .annotate(n=Count("id"))
        .order_by("-n")[:5]
    )
    active = Sprint.objects.filter(workspace=workspace, state=SprintState.ACTIVE).select_related("project")
    return {
        "workspace": workspace.name,
        "period_days": days,
        "generated_at": timezone.now().isoformat(),
        "totals": {
            "created": created.count(),
            "resolved": resolved.count(),
            "open": issues.exclude(status__category=StatusCategory.DONE).count(),
            "overdue": issues.filter(due_date__lt=today).exclude(status__category=StatusCategory.DONE).count(),
        },
        "projects": per_project,
        "top_contributors": [
            {"name": t["assignee__full_name"] or t["assignee__email"].split("@")[0], "resolved": t["n"]} for t in top
        ],
        "active_sprints": [
            {"project": s.project.key, "name": s.name, "ends": s.end_date.isoformat() if s.end_date else None}
            for s in active
        ],
    }


def render_report_text(report):
    t = report["totals"]
    lines = [
        f"Weekly report for {report['workspace']} (last {report['period_days']} days)",
        "",
        f"  Created: {t['created']}   Resolved: {t['resolved']}   Open: {t['open']}   Overdue: {t['overdue']}",
        "",
        "Projects",
    ]
    for p in report["projects"]:
        lines.append(f"  {p['key']:<8} open {p['open']:<4} +{p['created']} created  -{p['resolved']} resolved   {p['name']}")
    if report["top_contributors"]:
        lines += ["", "Top contributors"]
        lines += [f"  {c['name']}: {c['resolved']} resolved" for c in report["top_contributors"]]
    if report["active_sprints"]:
        lines += ["", "Active sprints"]
        lines += [f"  {s['project']} - {s['name']} (ends {s['ends']})" for s in report["active_sprints"]]
    return "\n".join(lines)
