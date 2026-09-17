'''Helpers to record admin audit events (never log secrets).'''

from admin_panel.models.audit import AdminAuditLog

SECRET_KEYS = {
    'password',
    'token',
    'access',
    'refresh',
    'secret',
    'api_key',
    'authorization',
}


def _scrub(value):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if str(key).lower() in SECRET_KEYS:
                out[key] = '[redacted]'
            else:
                out[key] = _scrub(item)
        return out
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return value


def record_admin_action(
    *,
    actor=None,
    action='other',
    target_type='',
    target_id='',
    summary='',
    reason='',
    previous_state=None,
    new_state=None,
    metadata=None,
):
    email = ''
    if actor is not None:
        email = getattr(actor, 'email', '') or ''
    return AdminAuditLog.objects.create(
        actor=actor if getattr(actor, 'pk', None) else None,
        actor_email=email,
        action=action,
        target_type=str(target_type or '')[:64],
        target_id=str(target_id or '')[:64],
        summary=str(summary or '')[:255],
        reason=reason or '',
        previous_state=_scrub(previous_state or {}),
        new_state=_scrub(new_state or {}),
        metadata=_scrub(metadata or {}),
    )
