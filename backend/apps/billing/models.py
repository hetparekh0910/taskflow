from django.db import models


class StripeEvent(models.Model):
    """Processed Stripe event ids - makes webhook handling idempotent."""

    event_id = models.CharField(max_length=100, unique=True)
    type = models.CharField(max_length=100)
    processed_at = models.DateTimeField(auto_now_add=True)
