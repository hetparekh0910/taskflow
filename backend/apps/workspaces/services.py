from django.db import transaction
from django.utils import timezone

from apps.billing import plans

from .models import Invitation, Membership, Role, Workspace


@transaction.atomic
def create_workspace(name, owner):
    ws = Workspace.objects.create(name=name, slug=Workspace.make_slug(name))
    Membership.objects.create(user=owner, workspace=ws, role=Role.OWNER)
    return ws


@transaction.atomic
def accept_invitation(invite: Invitation, user):
    # The invite was counted as a pending seat, so no extra limit check is needed.
    Membership.objects.get_or_create(user=user, workspace=invite.workspace, defaults={"role": invite.role})
    invite.accepted_at = timezone.now()
    invite.save(update_fields=["accepted_at"])
    from apps.webhooks.events import emit

    emit(invite.workspace, "member.joined", {"user": {"id": user.id, "email": user.email}, "role": invite.role})
    return invite.workspace


def check_can_add_member(workspace):
    plans.enforce(workspace, "members", 1)
