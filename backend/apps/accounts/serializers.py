from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

User = get_user_model()

COLORS = ["#6366f1", "#ec4899", "#f59e0b", "#10b981", "#3b82f6", "#8b5cf6", "#ef4444", "#14b8a6"]


class UserSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "display_name", "avatar_color"]
        read_only_fields = ["id", "email", "display_name"]


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    workspace_name = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=100)
    invite_token = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ["email", "password", "full_name", "workspace_name", "invite_token"]

    def validate_email(self, value):
        value = value.lower()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated):
        validated.pop("workspace_name", None)
        validated.pop("invite_token", None)
        password = validated.pop("password")
        user = User.objects.create_user(password=password, **validated)
        user.avatar_color = COLORS[user.id % len(COLORS)]
        user.save(update_fields=["avatar_color"])
        return user
