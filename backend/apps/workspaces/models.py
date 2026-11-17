import secrets

from django.conf import settings
from django.db import models
from django.utils.text import slugify


class Role(models.TextChoices):
    OWNER = "owner", "Owner"
    ADMIN = "admin", "Admin"
    MEMBER = "member", "Member"
    VIEWER = "viewer", "Viewer"


ROLE_RANK = {Role.VIEWER: 0, Role.MEMBER: 1, Role.ADMIN: 2, Role.OWNER: 3}


class Plan(models.TextChoices):
    FREE = "free", "Free"
    PRO = "pro", "Pro"
    BUSINESS = "business", "Business"


class Workspace(models.Model):
    """The tenant. Every other tenant table carries a FK to this."""

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=60, unique=True)
    plan = models.CharField(max_length=20, choices=Plan.choices, default=Plan.FREE)
    stripe_customer_id = models.CharField(max_length=100, blank=True)
    stripe_subscription_id = models.CharField(max_length=100, blank=True)
    subscription_status = models.CharField(max_length=30, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @staticmethod
    def make_slug(name):
        base = slugify(name)[:50] or "workspace"
        slug, i = base, 1
        while Workspace.objects.filter(slug=slug).exists():
            i += 1
            slug = f"{base}-{i}"
        return slug


class Membership(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "workspace")

    def __str__(self):
        return f"{self.user} @ {self.workspace} ({self.role})"

    def at_least(self, role):
        return ROLE_RANK[self.role] >= ROLE_RANK[role]


def _token():
    return secrets.token_urlsafe(24)


class Invitation(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField()
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)
    token = models.CharField(max_length=64, unique=True, default=_token)
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    accepted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
