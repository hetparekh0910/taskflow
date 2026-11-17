from rest_framework import serializers

from .models import EVENTS, Webhook, WebhookDelivery
from .tasks import assert_url_is_safe


class WebhookSerializer(serializers.ModelSerializer):
    class Meta:
        model = Webhook
        fields = ["id", "url", "events", "active", "description", "secret", "created_at"]
        read_only_fields = ["secret", "created_at"]

    def validate_url(self, value):
        try:
            assert_url_is_safe(value)
        except ValueError as e:
            raise serializers.ValidationError(str(e))
        return value

    def validate_events(self, value):
        if not value:
            raise serializers.ValidationError("Subscribe to at least one event, or ['*'] for all.")
        bad = [e for e in value if e != "*" and e not in EVENTS]
        if bad:
            raise serializers.ValidationError(f"Unknown events: {', '.join(bad)}")
        return value


class WebhookDeliverySerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookDelivery
        fields = [
            "id", "webhook", "event", "payload", "attempts", "success", "status_code",
            "response_body", "error", "next_retry_at", "created_at", "delivered_at",
        ]
