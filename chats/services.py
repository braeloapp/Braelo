'''
Shared chat helpers: participants, user-level blocks, history cursor,
and structured new-message notifications.
'''

from __future__ import annotations

import logging
from datetime import datetime

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import PermissionDenied, ValidationError

from chats.models import BlockedUser, Chat
from users.models import User

logger = logging.getLogger('chats.services')


def normalize_user_id(value) -> str:
    if value is None:
        return ''
    return str(value).strip()


def is_participant(chat, user_id) -> bool:
    uid = normalize_user_id(user_id)
    return uid in [normalize_user_id(p) for p in (chat.participants or [])]


def peer_user_id(chat, user_id) -> str | None:
    uid = normalize_user_id(user_id)
    for participant in chat.participants or []:
        peer = normalize_user_id(participant)
        if peer and peer != uid:
            return peer
    return None


def get_chat_for_participant(chat_id, user_id) -> Chat:
    chat = Chat.objects.filter(chat_id=chat_id).first()
    if not chat or not is_participant(chat, user_id):
        raise ValidationError({'chat': 'Chatroom not found'})
    return chat


def parse_before_cursor(raw):
    '''Parse ``?before=`` as an aware datetime. Returns None if blank.'''
    if raw in (None, ''):
        return None
    if isinstance(raw, datetime):
        value = raw
    else:
        value = parse_datetime(str(raw).strip())
        if value is None:
            raise ValidationError(
                {'before': 'Must be an ISO-8601 datetime.'}
            )
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_current_timezone())
    return value


def _int_ids(values):
    ids = []
    for value in values:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return ids


def blocked_counterpart_ids(user_id) -> set[str]:
    '''Users this account blocked, or who blocked this account.'''
    uid = normalize_user_id(user_id)
    if not uid:
        return set()
    rows = BlockedUser.objects.filter(
        __raw__={
            '$or': [
                {'blocker_id': uid},
                {'blocked_id': uid},
            ]
        }
    )
    counterparts = set()
    for row in rows:
        if row.blocker_id == uid:
            counterparts.add(row.blocked_id)
        else:
            counterparts.add(row.blocker_id)
    return counterparts


def blocked_owner_ids_for_listings(user_id) -> list[int]:
    return _int_ids(blocked_counterpart_ids(user_id))


def is_blocked_between(user_a, user_b) -> bool:
    a = normalize_user_id(user_a)
    b = normalize_user_id(user_b)
    if not a or not b or a == b:
        return False
    return bool(
        BlockedUser.objects.filter(blocker_id=a, blocked_id=b).first()
        or BlockedUser.objects.filter(blocker_id=b, blocked_id=a).first()
    )


def assert_not_blocked(user_a, user_b):
    if is_blocked_between(user_a, user_b):
        raise PermissionDenied('You cannot interact with this user.')


def assert_user_can_chat(user):
    if getattr(user, 'is_banned', False):
        raise PermissionDenied('This account is not allowed to use chat.')


def set_shared_rooms_blocked(user_a, user_b, blocked: bool):
    a = normalize_user_id(user_a)
    b = normalize_user_id(user_b)
    Chat.objects.filter(
        participants__all=[a, b],
        participants__size=2,
    ).update(set__is_blocked=blocked)


def block_user(blocker_id, blocked_id):
    blocker = normalize_user_id(blocker_id)
    blocked = normalize_user_id(blocked_id)
    if not blocked:
        raise ValidationError({'user_id': 'user_id is required.'})
    if blocker == blocked:
        raise ValidationError({'user_id': 'You cannot block yourself.'})
    if not User.objects.filter(id=blocked).exists():
        raise ValidationError({'user_id': 'User does not exist.'})
    existing = BlockedUser.objects.filter(
        blocker_id=blocker, blocked_id=blocked
    ).first()
    if existing:
        set_shared_rooms_blocked(blocker, blocked, True)
        return existing
    row = BlockedUser(blocker_id=blocker, blocked_id=blocked)
    row.save()
    set_shared_rooms_blocked(blocker, blocked, True)
    return row


def unblock_user(blocker_id, blocked_id):
    blocker = normalize_user_id(blocker_id)
    blocked = normalize_user_id(blocked_id)
    row = BlockedUser.objects.filter(
        blocker_id=blocker, blocked_id=blocked
    ).first()
    if not row:
        raise ValidationError({'user_id': 'This user is not blocked.'})
    row.delete()
    if not is_blocked_between(blocker, blocked):
        set_shared_rooms_blocked(blocker, blocked, False)
    return True


def notify_new_chat_message(chat, message, recipient_id):
    '''Best-effort structured FCM for a new chat message.

    Failures are logged and never raised to the message pipeline.
    '''
    recipient = normalize_user_id(recipient_id)
    sender = normalize_user_id(message.sender_id)
    if not recipient or recipient == sender:
        return
    if is_blocked_between(sender, recipient):
        return

    from helpers.notifications import chat_message_event

    payload = chat_message_event(
        recipient,
        chat.chat_id,
        sender,
        getattr(message, 'id', '') or '',
    )
    try:
        from notifications.serializers.events import EventNotificationSerializer

        serializer = EventNotificationSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        serializer.save()
    except Exception:
        logger.exception(
            'Chat push failed chat=%s recipient=%s',
            getattr(chat, 'chat_id', None),
            recipient,
        )
