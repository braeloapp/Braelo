'''Notification preference lookup and updates.'''

from __future__ import annotations

from notifications.models.preferences import NotificationPreference

PREFERENCE_KEYS = (
    'messages',
    'listing_activity',
    'business_activity',
    'marketing',
    'system_security',
    'admin_announcements',
)

EVENT_TO_PREFERENCE = {
    'new_message': 'messages',
    'listing_saved': 'listing_activity',
    'listing_created': 'listing_activity',
    'listing_updated': 'listing_activity',
    'listing_activated': 'listing_activity',
    'listing_deactivated': 'listing_activity',
    'business_created': 'business_activity',
    'business_activated': 'business_activity',
    'business_status': 'business_activity',
    'admin_announcement': 'admin_announcements',
    'admin': 'admin_announcements',
    'support_reply': 'system_security',
    'password_changed': 'system_security',
    'security_alert': 'system_security',
    'marketing': 'marketing',
    'offer': 'marketing',
}


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def preference_payload(user_id) -> dict:
    prefs = NotificationPreference.for_user(user_id)
    return {key: bool(getattr(prefs, key)) for key in PREFERENCE_KEYS}


def upsert_preferences(user_id, updates: dict) -> dict:
    prefs = NotificationPreference.for_user(user_id)
    changed = False
    for key in PREFERENCE_KEYS:
        if key not in updates:
            continue
        value = updates[key]
        if not isinstance(value, bool):
            continue
        if getattr(prefs, key) != value:
            setattr(prefs, key, value)
            changed = True
    if changed:
        prefs.save()
    return preference_payload(user_id)


def is_preference_enabled(user_id, event_type: str) -> bool:
    uid = _as_int(user_id)
    if uid is None:
        return False
    key = EVENT_TO_PREFERENCE.get((event_type or '').strip(), None)
    if key is None:
        return True
    prefs = NotificationPreference.for_user(uid)
    return bool(getattr(prefs, key, True))
