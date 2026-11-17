from django.contrib.auth import get_user_model
from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import generics, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import ROLE_RANK, Invitation, Membership, Role, Workspace
from .serializers import InvitationSerializer, MembershipSerializer, WorkspaceSerializer
from config.apidocs import *  # noqa

from .tenancy import WorkspaceScopedMixin

User = get_user_model()


class MyWorkspacesView(generics.ListCreateAPIView):
    """Workspaces the current user belongs to; creating one makes you its Owner."""

    serializer_class = WorkspaceSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None
    filter_backends = []

    def get_queryset(self):
        return Workspace.objects.filter(memberships__user=self.request.user).distinct()

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ws = services.create_workspace(ser.validated_data["name"], request.user)
        return Response(self.get_serializer(ws).data, status=status.HTTP_201_CREATED)


class WorkspaceDetailView(WorkspaceScopedMixin, APIView):
    role_map = {}

    def get_permissions(self):
        return super().get_permissions()

    @extend_schema(responses=WorkspaceSerializer, summary="Workspace details and your role in it")
    def get(self, request, workspace_slug):
        return Response(WorkspaceSerializer(request.workspace, context={"request": request}).data)

    @extend_schema(request=WorkspaceSerializer, responses=WorkspaceSerializer, summary="Rename the workspace (admin+)")
    def patch(self, request, workspace_slug):
        if not request.membership.at_least(Role.ADMIN):
            raise PermissionDenied("Admins only.")
        ser = WorkspaceSerializer(request.workspace, data=request.data, partial=True, context={"request": request})
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)

    @extend_schema(responses={204: None}, summary="Delete the workspace and ALL its data (owner only)")
    def delete(self, request, workspace_slug):
        if request.membership.role != Role.OWNER:
            raise PermissionDenied("Only the owner can delete a workspace.")
        request.workspace.delete()
        return Response(status=204)


class MemberViewSet(
    WorkspaceScopedMixin,
    mixins.ListModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Membership.objects.select_related("user")
    serializer_class = MembershipSerializer
    filter_backends = []
    pagination_class = None
    http_method_names = ["get", "patch", "delete", "head", "options"]
    role_map = {"list": Role.VIEWER, "partial_update": Role.ADMIN, "destroy": Role.VIEWER}

    def update(self, request, *args, **kwargs):
        target = self.get_object()
        new_role = request.data.get("role")
        if new_role not in Role.values:
            raise ValidationError({"role": "Invalid role."})
        me = request.membership
        # Admins cannot touch owners or grant owner; only owners can.
        if (target.role == Role.OWNER or new_role == Role.OWNER) and me.role != Role.OWNER:
            raise PermissionDenied("Only an owner can change ownership.")
        if target.role == Role.OWNER and new_role != Role.OWNER:
            if Membership.objects.filter(workspace=request.workspace, role=Role.OWNER).count() <= 1:
                raise ValidationError("A workspace needs at least one owner.")
        target.role = new_role
        target.save(update_fields=["role"])
        return Response(self.get_serializer(target).data)

    def destroy(self, request, *args, **kwargs):
        target = self.get_object()
        me = request.membership
        is_self = target.user_id == request.user.id
        if not is_self and not me.at_least(Role.ADMIN):
            raise PermissionDenied("Only admins can remove other members.")
        if target.role == Role.OWNER:
            if not is_self and me.role != Role.OWNER:
                raise PermissionDenied("Only an owner can remove an owner.")
            if Membership.objects.filter(workspace=request.workspace, role=Role.OWNER).count() <= 1:
                raise ValidationError("The last owner cannot leave. Transfer ownership first.")
        target.delete()
        return Response(status=204)


class InvitationViewSet(
    WorkspaceScopedMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Invitation.objects.select_related("invited_by", "workspace").filter(accepted_at__isnull=True)
    serializer_class = InvitationSerializer
    filter_backends = []
    pagination_class = None
    default_read_role = Role.ADMIN
    default_write_role = Role.ADMIN

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        email = ser.validated_data["email"].lower()
        if Membership.objects.filter(workspace=request.workspace, user__email__iexact=email).exists():
            raise ValidationError({"email": "That person is already a member."})
        if Invitation.objects.filter(workspace=request.workspace, email__iexact=email, accepted_at__isnull=True).exists():
            raise ValidationError({"email": "An invitation is already pending for this email."})
        services.check_can_add_member(request.workspace)
        invite = ser.save(workspace=request.workspace, invited_by=request.user, email=email)
        from apps.notifications.tasks import send_invitation_email

        transaction.on_commit(lambda: send_invitation_email.delay(invite.id))
        return Response(self.get_serializer(invite).data, status=201)


class InvitationLookupView(APIView):
    """Public: lets the sign-up page show which workspace an invite token is for."""

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(responses=InviteInfo, summary="Public: which workspace does this invite token belong to?")
    def get(self, request, token):
        invite = Invitation.objects.filter(token=token, accepted_at__isnull=True).select_related("workspace").first()
        if not invite:
            raise NotFound("Invitation not found or already used.")
        return Response({"email": invite.email, "workspace_name": invite.workspace.name, "role": invite.role})


class AcceptInvitationView(APIView):
    """Existing, signed-in users accept an invitation addressed to their email."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=TokenIn, responses=WorkspaceSerializer, summary="Signed-in user accepts an invitation addressed to their email")
    def post(self, request):
        invite = Invitation.objects.filter(
            token=request.data.get("token", ""), accepted_at__isnull=True, email__iexact=request.user.email
        ).first()
        if not invite:
            raise NotFound("Invitation not found, already used, or addressed to another email.")
        ws = services.accept_invitation(invite, request.user)
        return Response(WorkspaceSerializer(ws, context={"request": request}).data)
