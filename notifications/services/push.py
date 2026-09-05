'''FCM send + invalid token cleanup.'''

from __future__ import annotations

import logging

from firebase_admin import messaging

from users.models.devices import UserDeviceToken

logger = logging.getLogger('notifications.push')


def tokens_for_users(user_ids) -> list[str]:
    ids = []
    for value in user_ids or []:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    if not ids:
        return []
    tokens = []
    for device in UserDeviceToken.objects.filter(user_id__in=ids):
        token = (device.token or '').strip()
        if token:
            tokens.append(token)
    return tokens


def send_fcm(tokens, title, body, data=None):
    '''Send a multicast FCM message. Returns (success_count, failed_tokens).'''
    unique_tokens = list(dict.fromkeys([t for t in (tokens or []) if t]))
    if not unique_tokens:
        return 0, []

    payload = {str(key): str(value) for key, value in (data or {}).items()}
    message = messaging.MulticastMessage(
        notification=messaging.Notification(title=title, body=body),
        data=payload,
        tokens=unique_tokens,
    )
    try:
        response = messaging.send_each_for_multicast(message)
    except Exception:
        logger.exception('FCM multicast failed')
        return 0, unique_tokens

    failed = []
    for token, resp in zip(unique_tokens, response.responses):
        if resp.success:
            continue
        failed.append(token)
        error = getattr(resp, 'exception', None)
        code = getattr(error, 'code', '') if error is not None else ''
        if _is_invalid_token(code, str(error or '')):
            invalidate_token(token)
    return response.success_count, failed


def invalidate_token(token: str):
    if not token:
        return
    UserDeviceToken.objects(token=token).delete()


def _is_invalid_token(code: str, message: str) -> bool:
    haystack = f'{code} {message}'.lower()
    return any(
        marker in haystack
        for marker in (
            'registration-token-not-registered',
            'invalid-registration-token',
            'unregistered',
            'not-found',
        )
    )
