import csv
import io

from django.db.models import Count, IntegerField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import FileResponse, HttpResponse
from django_filters import rest_framework as filters
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.workspaces.models import Role
from config.apidocs import DashboardOut, SearchOut
from apps.workspaces.tenancy import WorkspaceScopedMixin

from . import services
from .models import (
    Attachment,
    Board,
    BoardColumn,
    Comment,
    Issue,
    Label,
    Project,
    SavedFilter,
    Sprint,
    SprintState,
    StatusCategory,
    WorkflowStatus,
    WorkflowTransition,
)
from .serializers import (
    AttachmentSerializer,
    BoardColumnSerializer,
    BoardSerializer,
    CommentSerializer,
    IssueSerializer,
    LabelSerializer,
    ProjectSerializer,
    SavedFilterSerializer,
    SprintSerializer,
    WorkflowStatusSerializer,
    WorkflowTransitionSerializer,
)


class TenantViewSet(WorkspaceScopedMixin, viewsets.ModelViewSet):
    """Base: tenant-scoped CRUD. Viewer reads, Member writes, Admin for structural objects."""

    default_read_role = Role.VIEWER
    default_write_role = Role.ADMIN


class ProjectViewSet(TenantViewSet):
    queryset = Project.objects.select_related("lead")
    serializer_class = ProjectSerializer
    search_fields = ["key", "name"]
    filterset_fields = ["archived"]
    ordering_fields = ["key", "name", "created_at"]
    role_map = {"board": Role.VIEWER, "export_csv": Role.VIEWER, "import_csv": Role.ADMIN}

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.annotate(
            total_issues=Count("issues", distinct=True),
            open_issues=Count("issues", filter=~Q(issues__status__category=StatusCategory.DONE), distinct=True),
        ).order_by("key")

    @action(detail=True, methods=["get"])
    def board(self, request, workspace_slug=None, pk=None):
        """Everything the Kanban UI needs in one call: columns, issues per column, allowed transitions."""
        project = self.get_object()
        board = project.boards.first()
        columns = list(board.columns.select_related("status").order_by("order", "id"))
        issues = (
            Issue.objects.filter(workspace=request.workspace, project=project)
            .select_related("assignee", "reporter", "status", "project")
            .prefetch_related("labels")
            .annotate(
                comment_count=Count("comments", distinct=True),
                attachment_count=Count("attachments", distinct=True),
            )
            .order_by("rank", "id")
        )
        # filters usable on the board as well
        assignee = request.query_params.get("assignee")
        sprint = request.query_params.get("sprint")
        q = request.query_params.get("q")
        if assignee == "me":
            issues = issues.filter(assignee=request.user)
        elif assignee:
            issues = issues.filter(assignee_id=assignee)
        if sprint == "active":
            issues = issues.filter(sprint__state=SprintState.ACTIVE)
        elif sprint:
            issues = issues.filter(sprint_id=sprint)
        if q:
            issues = issues.filter(Q(title__icontains=q) | Q(description__icontains=q))
        # Serialize the whole list in one go: a ListSerializer builds its child fields once, whereas creating
        # a serializer per card re-instantiates every nested field (measured ~10x slower for a 24-card board).
        issue_list = list(issues)
        ctx = self.get_serializer_context()
        by_status = {}
        for issue, payload in zip(issue_list, IssueSerializer(issue_list, many=True, context=ctx).data):
            by_status.setdefault(issue.status_id, []).append(payload)
        allowed = services.allowed_map(project, [c.status_id for c in columns])
        active_sprint = project.sprints.filter(state=SprintState.ACTIVE).first()
        data = {
            "id": board.id,
            "project": ProjectSerializer(project, context=self.get_serializer_context()).data,
            "columns": [
                {
                    "id": c.id,
                    "order": c.order,
                    "wip_limit": c.wip_limit,
                    "status": WorkflowStatusSerializer(c.status, context=self.get_serializer_context()).data,
                    "allowed_to": allowed.get(c.status_id, []),
                    "issues": by_status.get(c.status_id, []),
                }
                for c in columns
            ],
            "active_sprint": SprintSerializer(active_sprint, context=self.get_serializer_context()).data if active_sprint else None,
        }
        return Response(data)

    @action(detail=True, methods=["get"], url_path="export")
    def export_csv(self, request, workspace_slug=None, pk=None):
        project = self.get_object()
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["key", "type", "title", "status", "priority", "assignee", "story_points", "sprint", "due_date", "labels"])
        qs = project.issues.select_related("status", "assignee", "sprint").prefetch_related("labels")
        for i in qs:
            w.writerow(
                [
                    i.key, i.type, i.title, i.status.name, i.priority, i.assignee.email if i.assignee else "",
                    i.story_points or "", i.sprint.name if i.sprint else "", i.due_date or "",
                    ",".join(l.name for l in i.labels.all()),
                ]
            )
        resp = HttpResponse(out.getvalue(), content_type="text/csv")
        resp["Content-Disposition"] = f'attachment; filename="{project.key}-issues.csv"'
        return resp

    @action(detail=True, methods=["post"], url_path="import", parser_classes=[MultiPartParser, FormParser])
    def import_csv(self, request, workspace_slug=None, pk=None):
        """Import issues from CSV with header: title,type,priority,story_points,status,description."""
        project = self.get_object()
        upload = request.FILES.get("file")
        if not upload:
            raise ValidationError({"file": "Attach a CSV file."})
        if upload.size > 2 * 1024 * 1024:
            raise ValidationError({"file": "CSV must be under 2 MB."})
        text = upload.read().decode("utf-8-sig", errors="replace")
        rows = list(csv.DictReader(io.StringIO(text)))
        if len(rows) > 500:
            raise ValidationError({"file": "Max 500 rows per import."})
        statuses = {s.name.lower(): s for s in project.statuses.all()}
        created, errors = 0, []
        for n, row in enumerate(rows, start=2):
            title = (row.get("title") or "").strip()
            if not title:
                errors.append({"row": n, "error": "title is required"})
                continue
            ser = IssueSerializer(
                data={
                    "project": project.id,
                    "title": title,
                    "description": row.get("description", ""),
                    "type": (row.get("type") or "task").lower(),
                    "priority": (row.get("priority") or "medium").lower(),
                    "story_points": int(row["story_points"]) if (row.get("story_points") or "").strip().isdigit() else None,
                    **({"status": statuses[row["status"].strip().lower()].id}
                       if (row.get("status") or "").strip().lower() in statuses else {}),
                },
                context=self.get_serializer_context(),
            )
            if ser.is_valid():
                ser.save(workspace=request.workspace)
                created += 1
            else:
                errors.append({"row": n, "error": ser.errors})
        return Response({"created": created, "errors": errors})


class WorkflowStatusViewSet(TenantViewSet):
    queryset = WorkflowStatus.objects.all()
    serializer_class = WorkflowStatusSerializer
    filterset_fields = ["project"]
    pagination_class = None

    def get_queryset(self):
        return super().get_queryset().annotate(issue_count=Count("issues")).order_by("order", "id")

    def perform_create(self, serializer):
        status = serializer.save(workspace=self.request.workspace)
        # Make the new status visible on the project's board.
        for board in status.project.boards.all():
            BoardColumn.objects.get_or_create(
                workspace=self.request.workspace, board=board, status=status, defaults={"order": status.order}
            )

    def perform_destroy(self, instance):
        if instance.issues.exists():
            raise ValidationError("Move or delete the issues in this status first.")
        if instance.project.statuses.count() <= 2:
            raise ValidationError("A workflow needs at least two statuses.")
        instance.delete()


class WorkflowTransitionViewSet(TenantViewSet):
    queryset = WorkflowTransition.objects.all()
    serializer_class = WorkflowTransitionSerializer
    filterset_fields = ["project"]
    pagination_class = None

    @action(detail=False, methods=["post"], url_path="reset")
    def reset(self, request, workspace_slug=None):
        """Remove all transitions for a project => back to an open workflow."""
        project = self.get_object_in_workspace(Project, request.data.get("project"))
        n, _ = WorkflowTransition.objects.filter(workspace=request.workspace, project=project).delete()
        return Response({"deleted": n})

    @action(detail=False, methods=["post"], url_path="linear")
    def linear(self, request, workspace_slug=None):
        """Preset: each status may move to the next, previous, or straight to the last."""
        project = self.get_object_in_workspace(Project, request.data.get("project"))
        statuses = list(project.statuses.order_by("order", "id"))
        WorkflowTransition.objects.filter(workspace=request.workspace, project=project).delete()
        pairs = set()
        for i, s in enumerate(statuses):
            if i + 1 < len(statuses):
                pairs.add((s.id, statuses[i + 1].id))
            if i > 0:
                pairs.add((s.id, statuses[i - 1].id))
        WorkflowTransition.objects.bulk_create(
            [
                WorkflowTransition(workspace=request.workspace, project=project, from_status_id=a, to_status_id=b)
                for a, b in pairs
            ]
        )
        return Response({"created": len(pairs)})


class BoardColumnViewSet(
    WorkspaceScopedMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet
):
    queryset = BoardColumn.objects.select_related("status")
    serializer_class = BoardColumnSerializer
    default_write_role = Role.ADMIN
    pagination_class = None
    filterset_fields = ["board"]
    http_method_names = ["get", "patch", "head", "options"]


class SprintViewSet(TenantViewSet):
    queryset = Sprint.objects.all()
    serializer_class = SprintSerializer
    filterset_fields = ["project", "state"]
    role_map = {"start": Role.ADMIN, "close": Role.ADMIN, "burndown": Role.VIEWER}

    def get_queryset(self):
        return super().get_queryset().annotate(
            issue_count=Count("issues", distinct=True),
            total_points=Coalesce(Sum("issues__story_points"), Value(0), output_field=IntegerField()),
            done_points=Coalesce(
                Sum("issues__story_points", filter=Q(issues__status__category=StatusCategory.DONE)),
                Value(0),
                output_field=IntegerField(),
            ),
        ).order_by("-id")

    def perform_destroy(self, instance):
        if instance.state == SprintState.ACTIVE:
            raise ValidationError("Close the sprint before deleting it.")
        instance.delete()

    @action(detail=True, methods=["post"])
    def start(self, request, workspace_slug=None, pk=None):
        sprint = services.start_sprint(self.get_object())
        from apps.webhooks.events import emit

        emit(request.workspace, "sprint.started", {"sprint": {"id": sprint.id, "name": sprint.name}})
        return Response(self.get_serializer(self.get_queryset().get(pk=sprint.pk)).data)

    @action(detail=True, methods=["post"])
    def close(self, request, workspace_slug=None, pk=None):
        target = None
        if request.data.get("move_open_to"):
            target = self.get_object_in_workspace(Sprint, request.data["move_open_to"])
        sprint = services.close_sprint(self.get_object(), target)
        from apps.webhooks.events import emit

        emit(
            request.workspace,
            "sprint.closed",
            {"sprint": {"id": sprint.id, "name": sprint.name, "completed_points": sprint.completed_points}},
        )
        return Response(self.get_serializer(self.get_queryset().get(pk=sprint.pk)).data)

    @action(detail=True, methods=["get"])
    def burndown(self, request, workspace_slug=None, pk=None):
        return Response(services.burndown(self.get_object()))


class LabelViewSet(TenantViewSet):
    queryset = Label.objects.all()
    serializer_class = LabelSerializer
    pagination_class = None
    default_write_role = Role.MEMBER


class IssueFilter(filters.FilterSet):
    status = filters.NumberFilter(field_name="status_id")
    status_category = filters.CharFilter(field_name="status__category")
    assignee = filters.CharFilter(method="filter_assignee")
    label = filters.NumberFilter(field_name="labels__id")
    backlog = filters.BooleanFilter(method="filter_backlog")
    sprint = filters.CharFilter(method="filter_sprint")
    due_before = filters.DateFilter(field_name="due_date", lookup_expr="lte")
    overdue = filters.BooleanFilter(method="filter_overdue")
    q = filters.CharFilter(method="filter_q")

    class Meta:
        model = Issue
        fields = ["project", "type", "priority", "reporter", "parent"]

    def filter_assignee(self, qs, name, value):
        if value == "me":
            return qs.filter(assignee=self.request.user)
        if value == "none":
            return qs.filter(assignee__isnull=True)
        return qs.filter(assignee_id=value) if value.isdigit() else qs.none()

    def filter_backlog(self, qs, name, value):
        return qs.filter(sprint__isnull=True) if value else qs.filter(sprint__isnull=False)

    def filter_sprint(self, qs, name, value):
        if value == "active":
            return qs.filter(sprint__state=SprintState.ACTIVE)
        return qs.filter(sprint_id=value) if value.isdigit() else qs.none()

    def filter_overdue(self, qs, name, value):
        from django.utils import timezone

        if not value:
            return qs
        return qs.filter(due_date__lt=timezone.localdate()).exclude(status__category=StatusCategory.DONE)

    def filter_q(self, qs, name, value):
        # "WEB-12" style key lookup, otherwise full-text-ish match on title/description
        import re

        m = re.match(r"^([A-Za-z][A-Za-z0-9]+)-(\d+)$", value.strip())
        if m:
            return qs.filter(project__key=m.group(1).upper(), number=int(m.group(2)))
        return qs.filter(Q(title__icontains=value) | Q(description__icontains=value))


class IssueViewSet(TenantViewSet):
    queryset = Issue.objects.select_related("project", "status", "assignee", "reporter").prefetch_related("labels")
    serializer_class = IssueSerializer
    filterset_class = IssueFilter
    ordering_fields = ["rank", "created_at", "updated_at", "priority", "due_date", "story_points"]
    default_write_role = Role.MEMBER
    role_map = {"destroy": Role.ADMIN, "history": Role.VIEWER, "transitions": Role.VIEWER}

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .annotate(comment_count=Count("comments", distinct=True), attachment_count=Count("attachments", distinct=True))
            .order_by("rank", "id")
        )

    @action(detail=True, methods=["post"])
    def move(self, request, workspace_slug=None, pk=None):
        """Body: {status: id, above: id|null, below: id|null}. Used by the Kanban drag-and-drop."""
        issue = self.get_object()
        status = self.get_object_in_workspace(WorkflowStatus, request.data.get("status", issue.status_id))
        if status.project_id != issue.project_id:
            raise ValidationError({"status": "Status belongs to a different project."})
        above = below = None
        if request.data.get("above"):
            above = self.get_object_in_workspace(Issue, request.data["above"])
        if request.data.get("below"):
            below = self.get_object_in_workspace(Issue, request.data["below"])
        old_status_id = issue.status_id
        services.move_issue(issue, status, above, below)
        from apps.webhooks.events import emit

        if old_status_id != status.id:
            emit(
                request.workspace,
                "issue.moved",
                {"issue": {"id": issue.id, "key": issue.key, "title": issue.title},
                 "from": old_status_id, "to": status.id, "to_name": status.name},
            )
        fresh = self.get_queryset().get(pk=issue.pk)
        return Response(self.get_serializer(fresh).data)

    @action(detail=True, methods=["get"])
    def transitions(self, request, workspace_slug=None, pk=None):
        issue = self.get_object()
        ids = services.allowed_transitions(issue.project, issue.status)
        return Response(WorkflowStatusSerializer(issue.project.statuses.filter(id__in=ids), many=True).data)

    @action(detail=True, methods=["get"])
    def history(self, request, workspace_slug=None, pk=None):
        from apps.audit.models import AuditLog
        from apps.audit.serializers import AuditLogSerializer

        issue = self.get_object()
        logs = AuditLog.objects.filter(workspace=request.workspace, model="Issue", object_id=str(issue.pk))[:100]
        return Response(AuditLogSerializer(logs, many=True).data)


class CommentViewSet(TenantViewSet):
    queryset = Comment.objects.select_related("author")
    serializer_class = CommentSerializer
    filterset_fields = ["issue"]
    pagination_class = None
    default_write_role = Role.MEMBER

    def _check_owner(self, comment):
        if comment.author_id != self.request.user.id and not self.request.membership.at_least(Role.ADMIN):
            raise PermissionDenied("You can only change your own comments.")

    def perform_update(self, serializer):
        self._check_owner(serializer.instance)
        serializer.save()

    def perform_destroy(self, instance):
        self._check_owner(instance)
        instance.delete()


class AttachmentViewSet(
    WorkspaceScopedMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Attachment.objects.select_related("uploaded_by", "workspace")
    serializer_class = AttachmentSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filterset_fields = ["issue"]
    pagination_class = None
    default_write_role = Role.MEMBER
    role_map = {"download": Role.VIEWER}

    def perform_destroy(self, instance):
        if instance.uploaded_by_id != self.request.user.id and not self.request.membership.at_least(Role.ADMIN):
            raise PermissionDenied("You can only delete your own attachments.")
        instance.file.delete(save=False)
        instance.delete()

    @action(detail=True, methods=["get"])
    def download(self, request, workspace_slug=None, pk=None):
        """Files are served only through this membership-checked endpoint, never via a public /media URL."""
        att = self.get_object()
        resp = FileResponse(att.file.open("rb"), as_attachment=True, filename=att.name)
        resp["X-Content-Type-Options"] = "nosniff"
        return resp


class SavedFilterViewSet(TenantViewSet):
    queryset = SavedFilter.objects.all()
    serializer_class = SavedFilterSerializer
    pagination_class = None
    default_write_role = Role.MEMBER

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(Q(owner=self.request.user) | Q(shared=True))

    def perform_create(self, serializer):
        serializer.save(workspace=self.request.workspace, owner=self.request.user)

    def perform_update(self, serializer):
        if serializer.instance.owner_id != self.request.user.id:
            raise PermissionDenied("Only the owner can edit a saved filter.")
        serializer.save()

    def perform_destroy(self, instance):
        if instance.owner_id != self.request.user.id:
            raise PermissionDenied("Only the owner can delete a saved filter.")
        instance.delete()


class DashboardView(WorkspaceScopedMixin, APIView):
    @extend_schema(parameters=[OpenApiParameter("project", int, description="Limit to one project")], responses=DashboardOut, summary="Workspace analytics: totals, status/priority mix, 14-day flow, velocity, workload")
    def get(self, request, workspace_slug):
        project = None
        if request.query_params.get("project"):
            project = self.get_object_in_workspace(Project, request.query_params["project"])
        return Response(services.dashboard(request.workspace, project))


class SearchView(WorkspaceScopedMixin, APIView):
    """Quick global search (command palette): issues by key/title, projects by name."""

    @extend_schema(parameters=[OpenApiParameter("q", str, description="Text, or an issue key like WEB-12")], responses=SearchOut, summary="Quick search for the command palette")
    def get(self, request, workspace_slug):
        q = (request.query_params.get("q") or "").strip()
        if len(q) < 2:
            return Response({"issues": [], "projects": []})
        f = IssueFilter({"q": q}, queryset=Issue.objects.filter(workspace=request.workspace), request=request)
        issues = f.qs.select_related("project", "status")[:8]
        projects = Project.objects.filter(workspace=request.workspace).filter(Q(name__icontains=q) | Q(key__icontains=q))[:5]
        return Response(
            {
                "issues": [
                    {"id": i.id, "key": i.key, "title": i.title, "status": i.status.name, "project": i.project_id}
                    for i in issues
                ],
                "projects": [{"id": p.id, "key": p.key, "name": p.name} for p in projects],
            }
        )
