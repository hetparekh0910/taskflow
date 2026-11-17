import re

from django.conf import settings
from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.billing import plans
from apps.workspaces.tenancy import TenantPrimaryKeyRelatedField, WorkspaceMemberField

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
    StatusCategory,
    WorkflowStatus,
    WorkflowTransition,
)
from .services import check_transition, resolve_mentions

User = get_user_model()
KEY_RE = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")


class WorkflowStatusSerializer(serializers.ModelSerializer):
    project = TenantPrimaryKeyRelatedField(queryset=Project.objects.all())
    issue_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = WorkflowStatus
        fields = ["id", "project", "name", "category", "order", "color", "issue_count"]

    def validate(self, attrs):
        if self.instance is not None and "project" in attrs and attrs["project"].id != self.instance.project_id:
            raise serializers.ValidationError("A status cannot move between projects.")
        return attrs


class WorkflowTransitionSerializer(serializers.ModelSerializer):
    project = TenantPrimaryKeyRelatedField(queryset=Project.objects.all())
    from_status = TenantPrimaryKeyRelatedField(queryset=WorkflowStatus.objects.all())
    to_status = TenantPrimaryKeyRelatedField(queryset=WorkflowStatus.objects.all())

    class Meta:
        model = WorkflowTransition
        fields = ["id", "project", "from_status", "to_status"]

    def validate(self, attrs):
        p, a, b = attrs["project"], attrs["from_status"], attrs["to_status"]
        if a.project_id != p.id or b.project_id != p.id:
            raise serializers.ValidationError("Both statuses must belong to the project.")
        if a.id == b.id:
            raise serializers.ValidationError("A transition must connect two different statuses.")
        return attrs


class BoardColumnSerializer(serializers.ModelSerializer):
    status = WorkflowStatusSerializer(read_only=True)
    status_id = TenantPrimaryKeyRelatedField(
        queryset=WorkflowStatus.objects.all(), source="status", write_only=True, required=False
    )

    class Meta:
        model = BoardColumn
        fields = ["id", "board", "status", "status_id", "order", "wip_limit"]
        read_only_fields = ["board"]


class BoardSerializer(serializers.ModelSerializer):
    columns = BoardColumnSerializer(many=True, read_only=True)

    class Meta:
        model = Board
        fields = ["id", "project", "name", "columns"]


class ProjectSerializer(serializers.ModelSerializer):
    lead = WorkspaceMemberField(required=False, allow_null=True, queryset=User.objects.all())
    lead_detail = UserSerializer(source="lead", read_only=True)
    open_issues = serializers.IntegerField(read_only=True, default=0)
    total_issues = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Project
        fields = [
            "id", "key", "name", "description", "lead", "lead_detail", "archived",
            "open_issues", "total_issues", "created_at",
        ]
        read_only_fields = ["created_at"]

    def validate_key(self, value):
        value = value.upper().strip()
        if not KEY_RE.match(value):
            raise serializers.ValidationError("2-10 characters, letters/digits, starting with a letter (e.g. WEB).")
        if self.instance is not None and value != self.instance.key:
            raise serializers.ValidationError("The project key cannot be changed.")
        ws = self.context["workspace"]
        qs = Project.objects.filter(workspace=ws, key=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A project with this key already exists in your workspace.")
        return value

    def create(self, validated):
        plans.enforce(validated["workspace"], "projects", 1)
        project = super().create(validated)
        project.create_default_workflow()
        return project


class LabelSerializer(serializers.ModelSerializer):
    class Meta:
        model = Label
        fields = ["id", "name", "color"]

    def validate_name(self, value):
        qs = Label.objects.filter(workspace=self.context["workspace"], name__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Label already exists.")
        return value


class SprintSerializer(serializers.ModelSerializer):
    project = TenantPrimaryKeyRelatedField(queryset=Project.objects.all())
    issue_count = serializers.IntegerField(read_only=True, default=0)
    total_points = serializers.IntegerField(read_only=True, default=0)
    done_points = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Sprint
        fields = [
            "id", "project", "name", "goal", "start_date", "end_date", "state",
            "started_at", "closed_at", "committed_points", "completed_points",
            "issue_count", "total_points", "done_points",
        ]
        read_only_fields = ["state", "started_at", "closed_at", "committed_points", "completed_points"]

    def validate(self, attrs):
        s, e = attrs.get("start_date"), attrs.get("end_date")
        if self.instance:
            s = s or self.instance.start_date
            e = e or self.instance.end_date
        if s and e and e < s:
            raise serializers.ValidationError({"end_date": "End date must be after the start date."})
        if self.instance is not None and "project" in attrs and attrs["project"].id != self.instance.project_id:
            raise serializers.ValidationError({"project": "Cannot move a sprint to another project."})
        return attrs


class IssueSerializer(serializers.ModelSerializer):
    project = TenantPrimaryKeyRelatedField(queryset=Project.objects.all())
    status = TenantPrimaryKeyRelatedField(queryset=WorkflowStatus.objects.all(), required=False)
    sprint = TenantPrimaryKeyRelatedField(queryset=Sprint.objects.all(), required=False, allow_null=True)
    parent = TenantPrimaryKeyRelatedField(queryset=Issue.objects.all(), required=False, allow_null=True)
    labels = TenantPrimaryKeyRelatedField(queryset=Label.objects.all(), many=True, required=False)
    assignee = WorkspaceMemberField(required=False, allow_null=True, queryset=User.objects.all())

    key = serializers.CharField(read_only=True)
    assignee_detail = UserSerializer(source="assignee", read_only=True)
    reporter_detail = UserSerializer(source="reporter", read_only=True)
    status_detail = WorkflowStatusSerializer(source="status", read_only=True)
    label_details = LabelSerializer(source="labels", many=True, read_only=True)
    comment_count = serializers.IntegerField(read_only=True, default=0)
    attachment_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Issue
        fields = [
            "id", "key", "number", "project", "type", "title", "description", "status", "status_detail",
            "priority", "assignee", "assignee_detail", "reporter", "reporter_detail", "sprint", "parent",
            "story_points", "labels", "label_details", "due_date", "rank", "resolved_at",
            "created_at", "updated_at", "comment_count", "attachment_count",
        ]
        read_only_fields = ["number", "reporter", "rank", "resolved_at", "created_at", "updated_at"]

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Title is required.")
        return value

    def validate_story_points(self, value):
        if value is not None and value > 100:
            raise serializers.ValidationError("Story points must be 100 or fewer.")
        return value

    def validate(self, attrs):
        project = attrs.get("project") or (self.instance.project if self.instance else None)
        if self.instance is not None and "project" in attrs and attrs["project"].id != self.instance.project_id:
            raise serializers.ValidationError({"project": "Use the move-project flow; direct change is not allowed."})
        if project.archived and self.instance is None:
            raise serializers.ValidationError({"project": "This project is archived."})
        status = attrs.get("status")
        if status is not None and status.project_id != project.id:
            raise serializers.ValidationError({"status": "Status belongs to a different project."})
        sprint = attrs.get("sprint")
        if sprint is not None:
            if sprint.project_id != project.id:
                raise serializers.ValidationError({"sprint": "Sprint belongs to a different project."})
            if sprint.state == "closed":
                raise serializers.ValidationError({"sprint": "Cannot add issues to a closed sprint."})
        parent = attrs.get("parent")
        if parent is not None:
            if parent.project_id != project.id:
                raise serializers.ValidationError({"parent": "Parent must be in the same project."})
            if self.instance is not None and parent.pk == self.instance.pk:
                raise serializers.ValidationError({"parent": "An issue cannot be its own parent."})
        if self.instance is not None and status is not None and status.id != self.instance.status_id:
            check_transition(project, self.instance.status, status)
        return attrs

    def create(self, validated):
        request = self.context["request"]
        project = validated["project"]
        labels = validated.pop("labels", [])
        status = validated.pop("status", None) or project.statuses.order_by("order", "id").first()
        if status is None:
            raise serializers.ValidationError({"project": "Project has no workflow statuses."})
        issue = Issue(
            number=project.next_issue_number(),
            reporter=request.user,
            status=status,
            rank=Issue.next_rank(project, status),
            **validated,
        )
        if status.category == StatusCategory.DONE:
            from django.utils import timezone

            issue.resolved_at = timezone.now()
        issue.save()
        if labels:
            issue.labels.set(labels)
        return issue

    def update(self, instance, validated):
        from django.utils import timezone

        labels = validated.pop("labels", None)
        new_status = validated.get("status")
        if new_status is not None and new_status.id != instance.status_id:
            validated["rank"] = Issue.next_rank(instance.project, new_status)
            validated["resolved_at"] = timezone.now() if new_status.category == StatusCategory.DONE else None
        instance = super().update(instance, validated)
        if labels is not None:
            instance.labels.set(labels)
        return instance


class CommentSerializer(serializers.ModelSerializer):
    issue = TenantPrimaryKeyRelatedField(queryset=Issue.objects.all())
    author_detail = UserSerializer(source="author", read_only=True)
    mention_ids = serializers.PrimaryKeyRelatedField(source="mentions", many=True, read_only=True)

    class Meta:
        model = Comment
        fields = ["id", "issue", "author", "author_detail", "body", "mention_ids", "created_at", "updated_at"]
        read_only_fields = ["author", "created_at", "updated_at"]

    def validate_body(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Comment cannot be empty.")
        return value

    def _apply_mentions(self, comment, skip=()):
        from apps.notifications.models import Notification
        from apps.notifications.services import notify

        before = set(comment.mentions.values_list("id", flat=True))
        users = resolve_mentions(comment.workspace, comment.body)
        comment.mentions.set(users)
        author_id = comment.author_id
        for u in users:
            if u.id in before or u.id == author_id or u.id in skip:
                continue
            name = comment.author.display_name if comment.author else "Someone"
            notify(comment.workspace, u, Notification.Kind.MENTION,
                   f"{name} mentioned you on {comment.issue.key}", comment.issue, email=True)

    def create(self, validated):
        comment = Comment.objects.create(author=self.context["request"].user, **validated)
        self._apply_mentions(comment, skip=getattr(comment, "_already_notified", set()))
        return comment

    def update(self, instance, validated):
        validated.pop("issue", None)
        instance = super().update(instance, validated)
        self._apply_mentions(instance)
        return instance


class AttachmentSerializer(serializers.ModelSerializer):
    issue = TenantPrimaryKeyRelatedField(queryset=Issue.objects.all())
    uploaded_by_detail = UserSerializer(source="uploaded_by", read_only=True)
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = Attachment
        fields = ["id", "issue", "file", "name", "size", "content_type", "uploaded_by_detail", "download_url", "created_at"]
        read_only_fields = ["name", "size", "content_type", "created_at"]
        extra_kwargs = {"file": {"write_only": True}}

    BLOCKED_EXT = {".exe", ".bat", ".cmd", ".sh", ".msi", ".com", ".scr", ".js", ".vbs", ".ps1", ".dll"}

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_download_url(self, obj):
        ws = obj.workspace.slug
        return f"/api/w/{ws}/attachments/{obj.id}/download/"

    def validate_file(self, f):
        import os

        if f.size > settings.MAX_UPLOAD_BYTES:
            raise serializers.ValidationError(f"File too large (max {settings.MAX_UPLOAD_BYTES // (1024 * 1024)} MB).")
        if os.path.splitext(f.name)[1].lower() in self.BLOCKED_EXT:
            raise serializers.ValidationError("This file type is not allowed.")
        return f

    def create(self, validated):
        f = validated["file"]
        workspace = validated["workspace"]
        plans.enforce(workspace, "storage", f.size / (1024 * 1024))
        return Attachment.objects.create(
            uploaded_by=self.context["request"].user,
            name=f.name[:255],
            size=f.size,
            content_type=(getattr(f, "content_type", "") or "")[:100],
            **validated,
        )


class SavedFilterSerializer(serializers.ModelSerializer):
    project = TenantPrimaryKeyRelatedField(queryset=Project.objects.all(), required=False, allow_null=True)

    class Meta:
        model = SavedFilter
        fields = ["id", "name", "project", "query", "shared", "owner"]
        read_only_fields = ["owner"]
