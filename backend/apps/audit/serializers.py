from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = ["id", "actor", "actor_name", "action", "model", "object_id", "object_repr", "changes", "created_at"]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_actor_name(self, obj):
        return obj.actor.display_name if obj.actor else "System"
