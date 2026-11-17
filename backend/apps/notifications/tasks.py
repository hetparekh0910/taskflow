from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

from . import services


@shared_task
def send_notification_email(notification_id):
    from .models import Notification

    n = Notification.objects.select_related("user", "issue__project", "workspace").filter(pk=notification_id).first()
    if n is None or n.emailed:
        return
    link = settings.FRONTEND_URL
    if n.issue_id:
        link = f"{settings.FRONTEND_URL}/w/{n.workspace.slug}/issues/{n.issue_id}"
    send_mail(
        subject=f"[{n.workspace.name}] {n.get_kind_display()}",
        message=f"{n.message}\n\nOpen in TaskFlow: {link}",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[n.user.email],
        fail_silently=True,
    )
    n.emailed = True
    n.save(update_fields=["emailed"])


@shared_task
def send_invitation_email(invitation_id):
    from apps.workspaces.models import Invitation

    inv = Invitation.objects.select_related("workspace", "invited_by").filter(pk=invitation_id).first()
    if inv is None or inv.accepted_at:
        return
    inviter = inv.invited_by.display_name if inv.invited_by else "A teammate"
    link = f"{settings.FRONTEND_URL}/signup?invite={inv.token}"
    send_mail(
        subject=f"{inviter} invited you to {inv.workspace.name} on TaskFlow",
        message=f"{inviter} invited you to join '{inv.workspace.name}' as {inv.get_role_display()}.\n\nAccept: {link}",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[inv.email],
        fail_silently=True,
    )


@shared_task
def send_weekly_report(workspace_id):
    from apps.workspaces.models import Membership, Role, Workspace

    ws = Workspace.objects.filter(pk=workspace_id).first()
    if ws is None:
        return 0
    report = services.weekly_report(ws)
    recipients = list(
        Membership.objects.filter(workspace=ws, role__in=[Role.OWNER, Role.ADMIN]).values_list("user__email", flat=True)
    )
    if recipients:
        send_mail(
            subject=f"[{ws.name}] Weekly report",
            message=services.render_report_text(report),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=True,
        )
    return len(recipients)


@shared_task
def send_weekly_reports():
    """Celery beat: fan out one task per workspace."""
    from apps.workspaces.models import Workspace

    ids = list(Workspace.objects.values_list("id", flat=True))
    for wid in ids:
        send_weekly_report.delay(wid)
    return len(ids)
