"""Domain side-effects: webhook events + in-app/email notifications.

Runs on model signals so the behaviour is identical no matter which code path
(REST, CSV import, admin, management command) changes the data.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.notifications.models import Notification
from apps.notifications.services import notify
from apps.webhooks.events import emit
from apps.workspaces.tenancy import current_actor

from .models import Comment, Issue, Project


def _issue_payload(issue):
    return {
        "id": issue.id,
        "key": issue.key,
        "title": issue.title,
        "type": issue.type,
        "priority": issue.priority,
        "status": issue.status.name,
        "assignee": issue.assignee.email if issue.assignee_id else None,
        "project": issue.project.key,
    }


@receiver(post_save, sender=Project)
def project_saved(sender, instance, created, **kwargs):
    if created:
        emit(instance.workspace, "project.created", {"id": instance.id, "key": instance.key, "name": instance.name})


@receiver(post_save, sender=Issue)
def issue_saved(sender, instance, created, **kwargs):
    actor = current_actor.get()
    ws = instance.workspace
    if created:
        emit(ws, "issue.created", _issue_payload(instance))
        if instance.assignee_id and instance.assignee_id != getattr(actor, "id", None):
            notify(ws, instance.assignee, Notification.Kind.ASSIGNED,
                   f"{instance.key} was assigned to you: {instance.title}", instance, email=True)
        return

    old = getattr(instance, "_audit_old", None)
    if old is None:
        return
    emit(ws, "issue.updated", {**_issue_payload(instance), "changed": _changed_fields(old, instance)})

    actor_id = getattr(actor, "id", None)
    if instance.assignee_id and instance.assignee_id != old.assignee_id and instance.assignee_id != actor_id:
        notify(ws, instance.assignee, Notification.Kind.ASSIGNED,
               f"{instance.key} was assigned to you: {instance.title}", instance, email=True)
    if instance.status_id != old.status_id:
        for user in {instance.assignee, instance.reporter}:
            if user and user.id != actor_id:
                notify(ws, user, Notification.Kind.STATUS,
                       f"{instance.key} moved to {instance.status.name}", instance)


def _changed_fields(old, new):
    names = ["title", "description", "type", "priority", "status_id", "assignee_id", "sprint_id",
             "story_points", "due_date", "parent_id"]
    return [n.replace("_id", "") for n in names if getattr(old, n) != getattr(new, n)]


@receiver(post_save, sender=Comment)
def comment_saved(sender, instance, created, **kwargs):
    if not created:
        return
    ws = instance.workspace
    issue = instance.issue
    author = instance.author
    emit(ws, "comment.created", {
        "id": instance.id, "issue": issue.key, "author": author.email if author else None, "body": instance.body[:500],
    })
    # Mentions are resolved in the serializer *after* create(), so notify from there too.
    notified = set()
    for user in {issue.assignee, issue.reporter}:
        if user and (not author or user.id != author.id):
            notify(ws, user, Notification.Kind.COMMENT,
                   f"{author.display_name if author else 'Someone'} commented on {issue.key}", issue)
            notified.add(user.id)
    instance._already_notified = notified
