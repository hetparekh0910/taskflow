"""python manage.py seed_demo [--reset]

Builds two fully separate demo companies so tenant isolation is visible in the UI:
  * Acme Robotics (Pro plan)  - sign in as alice@acme.test / demo12345  (owner)
  * Globex Labs  (Free plan)  - sign in as gina@globex.test / demo12345 (owner)
alice is also a Viewer in Globex, which shows per-workspace roles + the workspace switcher.
"""
import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.projects.models import (
    Comment, Issue, Label, Project, Sprint, SprintState, StatusCategory, WorkflowTransition,
)
from apps.webhooks.models import Webhook
from apps.workspaces.models import Invitation, Membership, Role, Workspace
from apps.workspaces.tenancy import current_actor

PASSWORD = "demo12345"
COLORS = ["#6366f1", "#ec4899", "#f59e0b", "#10b981", "#3b82f6", "#8b5cf6", "#ef4444", "#14b8a6"]

ACME_USERS = [
    ("alice@acme.test", "Alice Johnson", Role.OWNER),
    ("bob@acme.test", "Bob Martinez", Role.ADMIN),
    ("carol@acme.test", "Carol Chen", Role.MEMBER),
    ("dave@acme.test", "Dave Okafor", Role.MEMBER),
    ("erin@acme.test", "Erin Walsh", Role.VIEWER),
]

WEB_BACKLOG = [
    ("story", "User can sign in with Google", "high", 5, "frontend"),
    ("bug", "Checkout button unresponsive on Safari", "highest", 3, "bug"),
    ("task", "Migrate image assets to CDN", "medium", 3, "devops"),
    ("story", "Add dark mode to the dashboard", "low", 5, "frontend"),
    ("bug", "Order total rounds incorrectly for JPY", "high", 2, "bug"),
    ("task", "Write onboarding email templates", "medium", 2, "content"),
    ("story", "Wishlist: share via link", "medium", 8, "frontend"),
    ("task", "Upgrade Postgres to 16", "high", 5, "devops"),
    ("bug", "Search ignores accented characters", "medium", 3, "bug"),
    ("task", "Audit third-party scripts for performance", "low", 3, "devops"),
    ("story", "Product comparison table", "medium", 8, "frontend"),
    ("task", "Set up error budget dashboards", "low", 2, "devops"),
]
API_ISSUES = [
    ("story", "Public REST API v2: pagination", "high", 5, "backend"),
    ("task", "Rate limit per API key", "high", 3, "backend"),
    ("bug", "Webhook retries not respecting backoff", "highest", 2, "bug"),
    ("task", "OpenAPI spec cleanup", "low", 2, "docs"),
    ("story", "Bulk import endpoint", "medium", 8, "backend"),
    ("task", "Add request-id logging", "medium", 1, "backend"),
]
MOBILE_ISSUES = [
    ("story", "Push notifications for assigned issues", "high", 8, "mobile"),
    ("bug", "App crashes when offline on launch", "highest", 5, "bug"),
    ("task", "Update to latest React Native", "medium", 5, "mobile"),
    ("story", "Biometric login", "medium", 5, "mobile"),
]
COMMENTS = [
    "Reproduced this locally, looking into it now.",
    "I think this is related to the recent deploy.",
    "Added a failing test, fix incoming.",
    "Can we get a design review before I start?",
    "Blocked on credentials, pinged ops.",
    "Looks good to me. Moving to review.",
    "Updated the estimate after talking with the team.",
]


class Command(BaseCommand):
    help = "Create two demo tenants with realistic data"

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete existing demo data first")

    @transaction.atomic
    def handle(self, *args, **opts):
        from django.conf import settings

        settings.EMAIL_BACKEND = "django.core.mail.backends.dummy.EmailBackend"  # no console spam while seeding
        random.seed(7)
        current_actor.set(None)
        if opts["reset"]:
            Workspace.objects.filter(slug__in=["acme-robotics", "globex-labs"]).delete()
            User.objects.filter(email__endswith=("@acme.test")).delete()
            User.objects.filter(email__endswith=("@globex.test")).delete()
        if Workspace.objects.filter(slug="acme-robotics").exists():
            self.stdout.write("Demo data already exists (use --reset to rebuild).")
            return

        users = {}
        for i, (email, name, _) in enumerate(ACME_USERS):
            users[email] = self._user(email, name, i)
        acme = Workspace.objects.create(name="Acme Robotics", slug="acme-robotics", plan="pro", subscription_status="active")
        for email, _, role in ACME_USERS:
            Membership.objects.create(user=users[email], workspace=acme, role=role)
        Invitation.objects.create(workspace=acme, email="frank@acme.test", role=Role.MEMBER, invited_by=users["alice@acme.test"])
        labels = {n: Label.objects.create(workspace=acme, name=n, color=c) for n, c in [
            ("frontend", "#3b82f6"), ("backend", "#8b5cf6"), ("bug", "#ef4444"), ("devops", "#f59e0b"),
            ("docs", "#14b8a6"), ("mobile", "#ec4899"), ("content", "#64748b")]}
        team = [users[e] for e in ("alice@acme.test", "bob@acme.test", "carol@acme.test", "dave@acme.test")]

        web = self._project(acme, "WEB", "Web Storefront", "Customer-facing shop", users["alice@acme.test"])
        api = self._project(acme, "API", "Platform API", "Public developer API", users["bob@acme.test"])
        mob = self._project(acme, "MOB", "Mobile App", "iOS and Android clients", users["carol@acme.test"])
        self._linear_workflow(api)  # API project uses an enforced workflow

        # --- WEB: two closed sprints (velocity), one active sprint (burndown), backlog
        self._closed_sprint(web, "Sprint 1", 28, 14, team, labels, [
            ("story", "Product catalog grid", "high", 8), ("task", "Set up CI pipeline", "high", 3),
            ("story", "Cart persistence", "medium", 5), ("bug", "Fix 404 on product slugs", "high", 2),
            ("task", "Design tokens", "medium", 3), ("story", "Basic search", "medium", 5)], carry=1)
        self._closed_sprint(web, "Sprint 2", 14, 14, team, labels, [
            ("story", "Checkout flow v1", "highest", 8), ("task", "Stripe integration", "high", 5),
            ("bug", "Cart total mismatch", "high", 3), ("task", "Email receipts", "medium", 3),
            ("story", "Order history page", "medium", 5), ("task", "Accessibility pass", "low", 2)], carry=2)
        active = Sprint.objects.create(workspace=acme, project=web, name="Sprint 3", goal="Ship checkout polish and Google sign-in",
                                       state=SprintState.PLANNED)
        picks = WEB_BACKLOG[:6]
        issues = [self._issue(web, t, team, labels, sprint=active, day=None) for t in picks]
        self._start(active, backdate_days=7, length=14)
        self._simulate_progress(issues, web, days=7)
        for t in WEB_BACKLOG[6:]:  # backlog
            self._issue(web, t, team, labels)

        # --- API project
        for t in API_ISSUES:
            self._issue(api, t, team, labels)
        # --- MOB project
        for t in MOBILE_ISSUES:
            self._issue(mob, t, team, labels)

        # extras: due dates, comments, a webhook
        today = timezone.localdate()
        for issue in Issue.objects.filter(workspace=acme).exclude(status__category=StatusCategory.DONE)[:8]:
            issue.due_date = today + timedelta(days=random.randint(-3, 12))
            issue.save(update_fields=["due_date"])
        for issue in random.sample(list(Issue.objects.filter(workspace=acme)), 14):
            for _ in range(random.randint(1, 3)):
                Comment.objects.create(workspace=acme, issue=issue, author=random.choice(team), body=random.choice(COMMENTS))
        Webhook.objects.create(workspace=acme, url="https://example.com/taskflow-hook", events=["issue.created", "issue.moved", "sprint.closed"],
                               description="Slack bridge (demo)")

        # --- Globex (separate tenant, Free plan)
        gina = self._user("gina@globex.test", "Gina Alvarez", 3)
        gus = self._user("gus@globex.test", "Gus Petrov", 5)
        globex = Workspace.objects.create(name="Globex Labs", slug="globex-labs", plan="free")
        Membership.objects.create(user=gina, workspace=globex, role=Role.OWNER)
        Membership.objects.create(user=gus, workspace=globex, role=Role.MEMBER)
        Membership.objects.create(user=users["alice@acme.test"], workspace=globex, role=Role.VIEWER)
        ops = self._project(globex, "OPS", "Lab Operations", "Internal ops tracker", gina)
        gl = {n: Label.objects.create(workspace=globex, name=n) for n in ("urgent", "equipment")}
        for t in [("task", "Calibrate spectrometer", "high", 2, "equipment"), ("bug", "Freezer alarm false positives", "highest", 3, "urgent"),
                  ("task", "Order lab consumables", "medium", 1, "equipment"), ("story", "Visitor sign-in kiosk", "low", 5, "equipment")]:
            self._issue(ops, t, [gina, gus], gl)
        self._age_data()
        self.stdout.write(self.style.SUCCESS(
            "Seeded.\n  Acme Robotics  alice@acme.test / demo12345 (owner), bob@ (admin), carol@ + dave@ (member), erin@ (viewer)\n"
            "  Globex Labs    gina@globex.test / demo12345 (owner)\n  alice@acme.test is also a *Viewer* in Globex Labs."))

    # ------------------------------------------------------------------ helpers
    def _age_data(self):
        """Spread creation dates over the last ~3 weeks so charts/feeds look like a real, lived-in workspace,
        and leave only a handful of notifications unread."""
        from apps.audit.models import AuditLog
        from apps.notifications.models import Notification

        now = timezone.now()
        for model in (Issue, Comment, AuditLog, Notification):
            rows = list(model.objects.order_by("id").values_list("id", flat=True))
            n = len(rows) or 1
            for idx, pk in enumerate(rows):
                age = timedelta(days=21 * (1 - idx / n), hours=random.randint(0, 6))
                model.objects.filter(pk=pk).update(created_at=now - age)
        for issue in Issue.objects.filter(resolved_at__isnull=False):
            created = issue.created_at
            if issue.resolved_at < created:  # resolved can never precede creation
                Issue.objects.filter(pk=issue.pk).update(created_at=issue.resolved_at - timedelta(days=2))
        unread = list(Notification.objects.order_by("-created_at").values_list("id", flat=True)[:4])
        Notification.objects.exclude(id__in=unread).update(read=True)

    def _user(self, email, name, i):
        u = User.objects.create_user(email=email, password=PASSWORD, full_name=name)
        u.avatar_color = COLORS[i % len(COLORS)]
        u.save(update_fields=["avatar_color"])
        return u

    def _project(self, ws, key, name, desc, lead):
        p = Project.objects.create(workspace=ws, key=key, name=name, description=desc, lead=lead)
        p.create_default_workflow()
        return p

    def _linear_workflow(self, project):
        st = list(project.statuses.order_by("order"))
        for a, b in zip(st, st[1:]):
            WorkflowTransition.objects.create(workspace=project.workspace, project=project, from_status=a, to_status=b)
            WorkflowTransition.objects.create(workspace=project.workspace, project=project, from_status=b, to_status=a)

    def _issue(self, project, spec, team, labels, sprint=None, day=None, status=None):
        typ, title, prio, pts, *lab = spec if len(spec) == 5 else (*spec, None)
        todo = status or project.statuses.order_by("order").first()
        issue = Issue.objects.create(
            workspace=project.workspace, project=project, number=project.next_issue_number(), type=typ, title=title,
            priority=prio, story_points=pts, status=todo, reporter=random.choice(team), assignee=random.choice(team + [None]),
            sprint=sprint, rank=Issue.next_rank(project, todo),
            description=f"Deliver: {title}.\n\nAcceptance criteria:\n- works on all supported browsers\n- covered by tests",
        )
        if lab and lab[0] in labels:
            issue.labels.add(labels[lab[0]])
        return issue

    def _closed_sprint(self, project, name, start_ago, length, team, labels, specs, carry=0):
        today = timezone.now()
        start = today - timedelta(days=start_ago)
        s = Sprint.objects.create(
            workspace=project.workspace, project=project, name=name, state=SprintState.CLOSED,
            start_date=start.date(), end_date=(start + timedelta(days=length)).date(), started_at=start, closed_at=start + timedelta(days=length),
        )
        done = project.statuses.get(category=StatusCategory.DONE)
        committed = completed = 0
        for i, spec in enumerate(specs):
            issue = self._issue(project, spec, team, labels, sprint=s, status=done)
            issue.assignee = team[i % len(team)]
            issue.resolved_at = start + timedelta(days=min(length - 1, 2 + i * 2))
            issue.save(update_fields=["assignee", "resolved_at"])
            committed += spec[3]
            completed += spec[3]
        committed += carry * 2  # work that slipped
        Sprint.objects.filter(pk=s.pk).update(committed_points=committed, completed_points=completed)

    def _start(self, sprint, backdate_days, length):
        start = timezone.now() - timedelta(days=backdate_days)
        sprint.state = SprintState.ACTIVE
        sprint.started_at = start
        sprint.start_date = start.date()
        sprint.end_date = (start + timedelta(days=length)).date()
        sprint.committed_points = sum(i.story_points or 0 for i in sprint.issues.all())
        sprint.save()

    def _simulate_progress(self, issues, project, days):
        """Resolve some issues on past days so the burndown has a real shape."""
        st = {s.name: s for s in project.statuses.all()}
        now = timezone.now()
        plan = [(0, "Done", 2), (1, "Done", 4), (2, "In Progress", None), (3, "In Review", None), (4, "Done", 5)]
        for idx, name, ago in plan:
            if idx >= len(issues):
                continue
            i = issues[idx]
            i.status = st[name]
            i.rank = Issue.next_rank(project, st[name])
            if name == "Done":
                i.resolved_at = now - timedelta(days=days - ago)
            i.save()
