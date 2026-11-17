"""Automatic audit trail. Hooks create/update/delete on tracked models and records
who (from the request-scoped contextvar), what changed, and when."""
import datetime
import decimal

from django.db.models.signals import m2m_changed, post_delete, post_save, pre_delete, pre_save
from django.dispatch import receiver

from apps.workspaces.tenancy import current_actor

from .models import AuditLog

TRACKED = {
    "projects.Project", "projects.Issue", "projects.Sprint", "projects.Comment", "projects.Attachment",
    "projects.WorkflowStatus", "projects.WorkflowTransition", "projects.Label", "projects.BoardColumn",
    "workspaces.Membership", "webhooks.Webhook",
}
# Noisy or derived fields we never log
IGNORED_FIELDS = {"updated_at", "rank", "issue_counter", "secret"}


def _label(model_cls):
    return f"{model_cls._meta.app_label}.{model_cls.__name__}"


def _jsonable(v):
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return float(v)
    if v is None or isinstance(v, (str, int, float, bool, list, dict)):
        return v
    return str(v)


def _snapshot(instance):
    return {
        f.name: instance.__dict__.get(f.attname)
        for f in instance._meta.concrete_fields
        if f.name not in IGNORED_FIELDS and f.name not in ("id", "workspace")
    }


def _human(instance, fname):
    """Readable value for FK fields (e.g. status name instead of an id)."""
    field = instance._meta.get_field(fname)
    if field.is_relation:
        try:
            obj = getattr(instance, fname)
        except Exception:
            return instance.__dict__.get(field.attname)
        return str(obj) if obj is not None else None
    return instance.__dict__.get(field.attname)


def _write(instance, action, changes):
    ws_id = getattr(instance, "workspace_id", None)
    if ws_id is None:
        return
    actor = current_actor.get()
    if actor is not None and not getattr(actor, "pk", None):
        actor = None
    AuditLog.objects.create(
        workspace_id=ws_id,
        actor=actor,
        action=action,
        model=instance.__class__.__name__,
        object_id=str(instance.pk),
        object_repr=str(instance)[:255],
        changes=changes,
    )


@receiver(pre_save)
def capture_old(sender, instance, **kwargs):
    if _label(sender) not in TRACKED or instance.pk is None:
        return
    old = sender.objects.filter(pk=instance.pk).first()
    instance._audit_old = old  # also reused by notification/webhook signals


@receiver(post_save)
def log_save(sender, instance, created, **kwargs):
    if _label(sender) not in TRACKED:
        return
    if created:
        _write(instance, AuditLog.Action.CREATE, {k: _jsonable(v) for k, v in _snapshot(instance).items() if v not in (None, "")})
        return
    old = getattr(instance, "_audit_old", None)
    if old is None:
        return
    before, after = _snapshot(old), _snapshot(instance)
    changes = {}
    for name, new_val in after.items():
        if before.get(name) != new_val:
            changes[name] = {"old": _jsonable(_human(old, name)), "new": _jsonable(_human(instance, name))}
    if changes:
        _write(instance, AuditLog.Action.UPDATE, changes)


_deleting_workspaces = set()


@receiver(pre_delete)
def mark_workspace_deleting(sender, instance, **kwargs):
    from apps.workspaces.models import Workspace

    if sender is Workspace:
        _deleting_workspaces.add(instance.pk)


@receiver(post_delete)
def log_delete(sender, instance, **kwargs):
    from apps.workspaces.models import Workspace

    if sender is Workspace:
        _deleting_workspaces.discard(instance.pk)
        return
    if _label(sender) not in TRACKED:
        return
    # When a whole tenant is being deleted its audit trail goes with it; don't write rows that would dangle.
    if getattr(instance, "workspace_id", None) in _deleting_workspaces:
        return
    _write(instance, AuditLog.Action.DELETE, {k: _jsonable(v) for k, v in _snapshot(instance).items() if v not in (None, "")})


@receiver(m2m_changed)
def log_labels(sender, instance, action, pk_set, **kwargs):
    from apps.projects.models import Issue

    if not isinstance(instance, Issue) or sender is not Issue.labels.through:
        return
    if action in ("post_add", "post_remove") and pk_set:
        from apps.projects.models import Label

        names = list(Label.objects.filter(pk__in=pk_set).values_list("name", flat=True))
        _write(
            instance,
            AuditLog.Action.UPDATE,
            {"labels": {"old" if action == "post_remove" else "new": names}},
        )
