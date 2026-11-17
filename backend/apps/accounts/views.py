from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.workspaces.models import Invitation, Membership, Role, Workspace
from apps.workspaces.serializers import WorkspaceSerializer

from .serializers import RegisterSerializer, UserSerializer

User = get_user_model()


class ThrottledMixin:
    throttle_scope = "auth"


class LoginView(ThrottledMixin, TokenObtainPairView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, *args, **kwargs):
        # Accept email + password; SimpleJWT uses USERNAME_FIELD (= email).
        return super().post(request, *args, **kwargs)


class RefreshView(ThrottledMixin, TokenRefreshView):
    permission_classes = [AllowAny]
    authentication_classes = []


class RegisterView(ThrottledMixin, generics.GenericAPIView):
    """Create an account. Optionally creates a first workspace, or accepts an invitation."""

    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    authentication_classes = []

    @transaction.atomic
    def post(self, request):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = ser.save()
        invite_token = ser.initial_data.get("invite_token") or ""
        ws_name = (ser.initial_data.get("workspace_name") or "").strip()
        workspace = None

        if invite_token:
            invite = Invitation.objects.filter(
                token=invite_token, accepted_at__isnull=True, email__iexact=user.email
            ).first()
            if invite is None:
                transaction.set_rollback(True)
                return Response({"invite_token": ["Invalid or already used invitation."]}, status=400)
            from apps.workspaces.services import accept_invitation

            workspace = accept_invitation(invite, user)
        elif ws_name:
            from apps.workspaces.services import create_workspace

            workspace = create_workspace(ws_name, user)

        refresh = RefreshToken.for_user(user)
        data = {
            "user": UserSerializer(user).data,
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "workspace": WorkspaceSerializer(workspace, context={"request": request, "user": user}).data if workspace else None,
        }
        return Response(data, status=status.HTTP_201_CREATED)


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user
