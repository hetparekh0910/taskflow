"""Tenant isolation primitives (shared schema, `workspace` FK on every tenant row).

Defence in depth, three layers:
  1. TenantModel      - every tenant table has a non-null `workspace` FK.
  2. WorkspaceScopedMixin - every DRF view resolves the workspace from the URL,
     verifies the caller's membership, and filters the queryset by it.
  3. Cross-tenant tests  - apps/workspaces/tests prove user A can never read,
     write or delete workspace B's data.
"""
import contextvars

from django.db import models
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import NotAuthenticated, NotFound, PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated

from .models import ROLE_RANK, Membership, Role, Workspace

# The acting user for audit logging; set per request in WorkspaceScopedMixin.initial().
current_actor = contextvars.ContextVar("current_actor", default=None)


class TenantQuerySet(models.QuerySet):
    def for_workspace(self, workspace):
        return self.filter(workspace=workspace)


class TenantModel(models.Model):
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="+", editable=False
    )

    objects = TenantQuerySet.as_manager()

    class Meta:
        abstract = True


class RolePermission(BasePermission):
    """Per-view role matrix.

    A view declares `role_map = {"list": "viewer", "create": "member", ...}` and
    optionally `default_write_role` / `default_read_role`.
    """

    message = "Your role in this workspace does not allow this action."

    def has_permission(self, request, view):
        membership = getattr(request, "membership", None)
        if membership is None:
            return False
        role_map = getattr(view, "role_map", {})
        action = getattr(view, "action", None)
        if action in role_map:
            needed = role_map[action]
        elif request.method in SAFE_METHODS:
            needed = getattr(view, "default_read_role", Role.VIEWER)
        else:
            needed = getattr(view, "default_write_role", Role.MEMBER)
        return ROLE_RANK[membership.role] >= ROLE_RANK[needed]


class WorkspaceScopedMixin:
    """Resolves /api/w/<workspace_slug>/... and scopes everything to that tenant."""

    permission_classes = [IsAuthenticated, RolePermission]
    workspace_url_kwarg = "workspace_slug"

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)  # authentication runs here
        if not request.user.is_authenticated:
            raise NotAuthenticated()
        slug = kwargs.get(self.workspace_url_kwarg)
        workspace = Workspace.objects.filter(slug=slug).first()
        membership = None
        if workspace and request.user.is_authenticated:
            membership = Membership.objects.filter(user=request.user, workspace=workspace).first()
        # Same 404 whether the workspace is missing or the caller isn't a member:
        # we never confirm that another tenant exists.
        if membership is None:
            raise NotFound("Workspace not found.")
        request.workspace = workspace
        request.membership = membership
        current_actor.set(request.user)
        # Re-run permission checks now that membership is known.
        self.check_permissions(request)

    def check_permissions(self, request):
        # Before the workspace is resolved there is nothing to check yet.
        if not hasattr(request, "membership"):
            return
        super().check_permissions(request)

    @property
    def workspace(self):
        return self.request.workspace

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(workspace=self.request.workspace)

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["workspace"] = getattr(self.request, "workspace", None)
        return ctx

    def perform_create(self, serializer):
        serializer.save(workspace=self.request.workspace)

    def get_object_in_workspace(self, model, pk, **extra):
        """Fetch a related object, guaranteeing it belongs to the active workspace."""
        return get_object_or_404(model, pk=pk, workspace=self.request.workspace, **extra)


from rest_framework import serializers  # noqa: E402


class TenantPrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        qs = super().get_queryset()
        workspace = self.context.get("workspace")
        if workspace is None:
            raise PermissionDenied("No workspace in context.")
        if hasattr(qs.model, "workspace_id"):
            return qs.filter(workspace=workspace)
        return qs


class WorkspaceMemberField(serializers.PrimaryKeyRelatedField):
    """A user id that must belong to the active workspace."""

    def get_queryset(self):
        from django.contrib.auth import get_user_model

        workspace = self.context["workspace"]
        return get_user_model().objects.filter(memberships__workspace=workspace)
