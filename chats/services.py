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

from chats.models import BlockedUser, Chat, Message
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
    try:
        return bool(
            BlockedUser.objects.filter(blocker_id=a, blocked_id=b).first()
            or BlockedUser.objects.filter(blocker_id=b, blocked_id=a).first()
        )
    except Exception as exc:
        # CI / environments without a MongoEngine default connection
        message = str(exc).lower()
        if 'default connection' in message or 'not connected' in message:
            return False
        try:
            from mongoengine.connection import ConnectionFailure
        except ImportError:  # pragma: no cover
            raise
        if isinstance(exc, ConnectionFailure):
            return False
        raise



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


def inbox_group(user_id) -> str:
    return f'inbox_{normalize_user_id(user_id)}'


def _isoformat(value) -> str:
    if value is None:
        return timezone.now().isoformat()
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


def first_media_url(value):
    if value is None or value == '':
        return None
    if isinstance(value, (list, tuple)):
        for item in value:
            url = first_media_url(item)
            if url:
                return url
        return None
    return str(value)


def user_display_name(user) -> str:
    if user is None:
        return ''
    full = ' '.join(
        part
        for part in (
            getattr(user, 'first_name', None),
            getattr(user, 'last_name', None),
        )
        if part
    ).strip()
    for candidate in (
        getattr(user, 'name', None),
        full,
        getattr(user, 'username', None),
        getattr(user, 'email', None),
    ):
        text = str(candidate or '').strip()
        if text and text != 'temp_username':
            return text
    return ''


def message_preview(message) -> str:
    content = str(getattr(message, 'content', None) or '').strip()
    if content:
        return content
    if getattr(message, 'media_url', None):
        return 'Photo'
    return ''


def unread_count_for(chat, user_id) -> int:
    return Message.objects.filter(
        chat=chat, read=False, sender_id__ne=normalize_user_id(user_id)
    ).count()


def message_ws_payload(message, chat=None) -> dict:
    chat = chat or getattr(message, 'chat', None)
    chat_id = getattr(chat, 'chat_id', None) if chat is not None else None
    return {
        'type': 'message',
        'id': str(getattr(message, 'id', '') or ''),
        'sender_id': str(getattr(message, 'sender_id', '') or ''),
        'content': message.content or '',
        'created_at': _isoformat(getattr(message, 'created_at', None)),
        'read': bool(getattr(message, 'read', False)),
        'media_url': getattr(message, 'media_url', None) or None,
        'chat_id': chat_id,
    }


def history_payload(chat, before=None, limit=40) -> dict:
    limit = max(1, min(int(limit or 40), 50))
    queryset = Message.objects.filter(chat=chat).order_by('-created_at')
    if before is not None:
        queryset = queryset.filter(created_at__lt=before)
    rows = list(queryset[:limit])
    rows.reverse()
    return {
        'type': 'history',
        'chat_id': getattr(chat, 'chat_id', None),
        'messages': [message_ws_payload(row, chat) for row in rows],
        'has_more': len(rows) == limit,
    }


def fanout_chat_message(chat, message, sender_id, peer_id=None):
    '''Broadcast a saved message to the room and both inbox groups.'''
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    layer = get_channel_layer()
    if layer is None:
        return
    payload = message_ws_payload(message, chat)
    try:
        async_to_sync(layer.group_send)(
            chat.chat_id,
            {'type': 'chat_message', 'message': payload},
        )
    except Exception:
        logger.exception('WS room fanout failed chat=%s', getattr(chat, 'chat_id', None))

    preview = message_preview(message)
    created_at = payload['created_at']
    for uid in {normalize_user_id(sender_id), normalize_user_id(peer_id)}:
        if not uid:
            continue
        inbox = {
            'type': 'chat_updated',
            'chat_id': chat.chat_id,
            'last_message': preview,
            'message_created_at': created_at,
            'sender_id': str(sender_id),
            'unread_messages': unread_count_for(chat, uid),
            'media_url': payload.get('media_url'),
        }
        try:
            async_to_sync(layer.group_send)(
                inbox_group(uid),
                {'type': 'inbox_event', 'payload': inbox},
            )
        except Exception:
            logger.exception('WS inbox fanout failed user=%s', uid)


def fanout_messages_read(chat, reader_id):
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    layer = get_channel_layer()
    if layer is None:
        return
    payload = {
        'type': 'messages_read',
        'chat_id': chat.chat_id,
        'reader_id': str(reader_id),
    }
    try:
        async_to_sync(layer.group_send)(
            chat.chat_id,
            {'type': 'chat_event', 'payload': payload},
        )
    except Exception:
        logger.exception('WS read fanout failed chat=%s', getattr(chat, 'chat_id', None))
    peer = peer_user_id(chat, reader_id)
    for uid in {normalize_user_id(reader_id), normalize_user_id(peer)}:
        if not uid:
            continue
        inbox = {
            'type': 'chat_updated',
            'chat_id': chat.chat_id,
            'unread_messages': unread_count_for(chat, uid),
            'sender_id': str(reader_id),
        }
        try:
            async_to_sync(layer.group_send)(
                inbox_group(uid),
                {'type': 'inbox_event', 'payload': inbox},
            )
        except Exception:
            logger.exception('WS read inbox failed user=%s', uid)

