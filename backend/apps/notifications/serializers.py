from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    issue_key = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ["id", "kind", "message", "issue", "issue_key", "read", "created_at"]
        read_only_fields = ["kind", "message", "issue", "created_at"]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_issue_key(self, obj):
        return obj.issue.key if obj.issue_id else None
