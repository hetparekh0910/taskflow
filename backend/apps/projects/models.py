import os

from django.conf import settings
from django.db import models, transaction

from apps.workspaces.tenancy import TenantModel


class StatusCategory(models.TextChoices):
    TODO = "todo", "To do"
    IN_PROGRESS = "in_progress", "In progress"
    DONE = "done", "Done"


DEFAULT_STATUSES = [
    ("To Do", StatusCategory.TODO, "#94a3b8"),
    ("In Progress", StatusCategory.IN_PROGRESS, "#3b82f6"),
    ("In Review", StatusCategory.IN_PROGRESS, "#a855f7"),
    ("Done", StatusCategory.DONE, "#22c55e"),
]


class Project(TenantModel):
    key = models.CharField(max_length=10)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    lead = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    issue_counter = models.PositiveIntegerField(default=0)
    archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("workspace", "key")
        ordering = ["key"]

    def __str__(self):
        return f"{self.key} - {self.name}"

    def next_issue_number(self):
        with transaction.atomic():
            p = Project.objects.select_for_update().get(pk=self.pk)
            p.issue_counter += 1
            p.save(update_fields=["issue_counter"])
            return p.issue_counter

    def create_default_workflow(self):
        """Seed statuses, an (open) transition graph and a board for a new project."""
        statuses = []
        for i, (name, cat, color) in enumerate(DEFAULT_STATUSES):
            statuses.append(
                WorkflowStatus.objects.create(
                    workspace=self.workspace, project=self, name=name, category=cat, order=i, color=color
                )
            )
        board = Board.objects.create(workspace=self.workspace, project=self, name=f"{self.key} board")
        for i, s in enumerate(statuses):
            BoardColumn.objects.create(workspace=self.workspace, board=board, status=s, order=i)
        return board


class WorkflowStatus(TenantModel):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="statuses")
    name = models.CharField(max_length=50)
    category = models.CharField(max_length=20, choices=StatusCategory.choices, default=StatusCategory.TODO)
    order = models.PositiveIntegerField(default=0)
    color = models.CharField(max_length=7, default="#94a3b8")

    class Meta:
        ordering = ["order", "id"]
        unique_together = ("project", "name")

    def __str__(self):
        return self.name


class WorkflowTransition(TenantModel):
    """Allowed move from one status to another.

    If a project defines *no* transitions, every move is allowed (open workflow).
    Once at least one exists, only listed moves are permitted.
    """

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="transitions")
    from_status = models.ForeignKey(WorkflowStatus, on_delete=models.CASCADE, related_name="+")
    to_status = models.ForeignKey(WorkflowStatus, on_delete=models.CASCADE, related_name="+")

    class Meta:
        unique_together = ("from_status", "to_status")


class Board(TenantModel):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="boards")
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["id"]


class BoardColumn(TenantModel):
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="columns")
    status = models.ForeignKey(WorkflowStatus, on_delete=models.CASCADE, related_name="+")
    order = models.PositiveIntegerField(default=0)
    wip_limit = models.PositiveIntegerField(null=True, blank=True, help_text="Max issues; empty = no limit")

    class Meta:
        ordering = ["order", "id"]
        unique_together = ("board", "status")


class SprintState(models.TextChoices):
    PLANNED = "planned", "Planned"
    ACTIVE = "active", "Active"
    CLOSED = "closed", "Closed"


class Sprint(TenantModel):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="sprints")
    name = models.CharField(max_length=100)
    goal = models.TextField(blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    state = models.CharField(max_length=10, choices=SprintState.choices, default=SprintState.PLANNED)
    started_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    # Snapshot of committed points at start; drives the burndown ideal line.
    committed_points = models.PositiveIntegerField(default=0)
    completed_points = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return self.name


class Label(TenantModel):
    name = models.CharField(max_length=40)
    color = models.CharField(max_length=7, default="#64748b")

    class Meta:
        unique_together = ("workspace", "name")
        ordering = ["name"]


class IssueType(models.TextChoices):
    TASK = "task", "Task"
    BUG = "bug", "Bug"
    STORY = "story", "Story"
    EPIC = "epic", "Epic"


class Priority(models.TextChoices):
    LOWEST = "lowest", "Lowest"
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    HIGHEST = "highest", "Highest"


RANK_STEP = 1000.0


class Issue(TenantModel):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="issues")
    number = models.PositiveIntegerField()
    type = models.CharField(max_length=10, choices=IssueType.choices, default=IssueType.TASK)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.ForeignKey(WorkflowStatus, on_delete=models.RESTRICT, related_name="issues")
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_issues"
    )
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="reported_issues"
    )
    sprint = models.ForeignKey(Sprint, null=True, blank=True, on_delete=models.SET_NULL, related_name="issues")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children")
    story_points = models.PositiveSmallIntegerField(null=True, blank=True)
    labels = models.ManyToManyField(Label, blank=True, related_name="issues")
    due_date = models.DateField(null=True, blank=True)
    # Fractional rank: dragging an issue between two neighbours sets rank to their
    # midpoint, so a move touches exactly one row. Rebalanced when gaps get tiny.
    rank = models.FloatField(default=0, db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("project", "number")
        ordering = ["rank", "id"]
        indexes = [
            models.Index(fields=["workspace", "project", "status"]),
            models.Index(fields=["workspace", "assignee"]),
        ]

    @property
    def key(self):
        return f"{self.project.key}-{self.number}"

    def __str__(self):
        return f"{self.key}: {self.title}"

    @classmethod
    def next_rank(cls, project, status):
        last = cls.objects.filter(project=project, status=status).aggregate(m=models.Max("rank"))["m"]
        return (last or 0) + RANK_STEP

    @classmethod
    def rebalance(cls, project, status):
        for i, issue in enumerate(cls.objects.filter(project=project, status=status).order_by("rank", "id"), 1):
            cls.objects.filter(pk=issue.pk).update(rank=i * RANK_STEP)


class Comment(TenantModel):
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    body = models.TextField()
    mentions = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]


def attachment_path(instance, filename):
    return f"w{instance.workspace_id}/issues/{instance.issue_id}/{os.path.basename(filename)}"


class Attachment(TenantModel):
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="attachments")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    file = models.FileField(upload_to=attachment_path)
    name = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField(default=0)
    content_type = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class SavedFilter(TenantModel):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    name = models.CharField(max_length=80)
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    query = models.JSONField(default=dict)
    shared = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]
