'''Persist in-app notifications and optionally send FCM.'''

from __future__ import annotations

import logging

from django.utils import timezone

from notifications.models import Notification
from notifications.services.preferences import is_preference_enabled
from notifications.services.push import send_fcm, tokens_for_users

logger = logging.getLogger('notifications.delivery')


def _normalize_user_ids(values) -> list[int]:
    ids = []
    for value in values or []:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return ids


def _event_type(data: dict, fallback: str) -> str:
    if not isinstance(data, dict):
        return fallback
    return str(data.get('type') or fallback or '').strip()


def deliver_event_notification(validated_data: dict) -> Notification:
    '''Save the notification and send FCM to recipients who opted in.

    Missing device tokens are not an error. FCM failures never raise.
    '''
    payload = dict(validated_data)
    user_ids = _normalize_user_ids(payload.get('user_id'))
    payload['user_id'] = user_ids
    data = dict(payload.get('data') or {})
    event_type = _event_type(data, payload.get('type') or '')
    data.setdefault('type', event_type)
    data.setdefault('entity_type', payload.get('type') or '')
    data.setdefault('action', 'open')
    payload['data'] = data
    payload.setdefault('created_at', timezone.now())

    notification = Notification.objects.create(**payload)
    data['notification_id'] = str(notification.id)
    notification.data = data
    notification.save()

    fcm_recipients = [
        uid for uid in user_ids if is_preference_enabled(uid, event_type)
    ]
    tokens = tokens_for_users(fcm_recipients)
    if not tokens:
        return notification

    try:
        success_count, _failed = send_fcm(
            tokens,
            notification.title,
            notification.body,
            notification.data,
        )
        if success_count > 0:
            notification.mark_as_sent()
    except Exception:
        logger.exception(
            'Notification FCM failed id=%s users=%s',
            notification.id,
            user_ids,
        )
    return notification
