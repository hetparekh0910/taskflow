from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounts.serializers import UserSerializer

from .models import Invitation, Membership, Role, Workspace


class WorkspaceSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()

    class Meta:
        model = Workspace
        fields = ["id", "name", "slug", "plan", "subscription_status", "role", "created_at"]
        read_only_fields = ["slug", "plan", "subscription_status", "created_at"]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_role(self, obj):
        user = self.context.get("user")
        if user is None:
            request = self.context.get("request")
            user = request.user if request else None
        if user is None or not user.is_authenticated:
            return None
        m = Membership.objects.filter(workspace=obj, user=user).first()
        return m.role if m else None


class MembershipSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "user", "role", "joined_at"]
        read_only_fields = ["id", "user", "joined_at"]


class InvitationSerializer(serializers.ModelSerializer):
    invited_by_name = serializers.CharField(source="invited_by.display_name", read_only=True, default=None)
    workspace_name = serializers.CharField(source="workspace.name", read_only=True)

    class Meta:
        model = Invitation
        fields = ["id", "email", "role", "token", "workspace_name", "invited_by_name", "accepted_at", "created_at"]
        read_only_fields = ["id", "token", "accepted_at", "created_at"]

    def validate_role(self, value):
        if value == Role.OWNER:
            raise serializers.ValidationError("Invite as admin, then transfer ownership.")
        return value
