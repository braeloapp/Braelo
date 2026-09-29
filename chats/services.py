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

    Runs off the websocket critical path so delivery is not blocked by push.
    Failures are logged and never raised to the message pipeline.
    '''
    recipient = normalize_user_id(recipient_id)
    sender = normalize_user_id(getattr(message, 'sender_id', None))
    chat_id = getattr(chat, 'chat_id', None)
    message_id = getattr(message, 'id', '') or ''
    if not recipient or recipient == sender:
        return
    if is_blocked_between(sender, recipient):
        return

    def _send():
        try:
            from helpers.notifications import chat_message_event
            from notifications.serializers.events import EventNotificationSerializer

            payload = chat_message_event(
                recipient,
                chat_id,
                sender,
                message_id,
            )
            serializer = EventNotificationSerializer(data=payload)
            serializer.is_valid(raise_exception=True)
            serializer.save()
        except Exception:
            logger.exception(
                'Chat push failed chat=%s recipient=%s',
                chat_id,
                recipient,
            )

    import threading

    threading.Thread(target=_send, daemon=True).start()


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


def enrich_chat_for_viewer(record: dict, viewer_id) -> dict:
    '''Attach peer display name/picture fields for create/open chat responses.'''
    if not isinstance(record, dict):
        return record
    viewer = normalize_user_id(viewer_id)
    participants = record.get('participants') or []
    peer = None
    for participant in participants:
        pid = normalize_user_id(participant)
        if pid and pid != viewer:
            peer = pid
            break
    if not peer:
        receiver = record.get('receiver') or {}
        sender = record.get('sender') or {}
        receiver_id = normalize_user_id(receiver.get('user_id'))
        sender_id = normalize_user_id(sender.get('user_id'))
        if receiver_id and receiver_id != viewer:
            peer = receiver_id
        elif sender_id and sender_id != viewer:
            peer = sender_id

    receiver = record.get('receiver') or {}
    sender = record.get('sender') or {}
    if normalize_user_id(receiver.get('user_id')) == viewer:
        peer_type = (sender or {}).get('user_type')
    elif normalize_user_id(sender.get('user_id')) == viewer:
        peer_type = (receiver or {}).get('user_type')
    else:
        peer_type = (receiver or {}).get('user_type') or (sender or {}).get(
            'user_type'
        )

    if not peer:
        return attach_listing_payload(record)

    from users.models import Business

    if peer_type == 'business':
        business = Business.objects.filter(user_id=peer).first()
        record['business_picture'] = (
            first_media_url(getattr(business, 'business_logo', None))
            if business
            else None
        )
        record['business_name'] = (
            getattr(business, 'business_name', None) or 'Business'
        )
        if business is None:
            fallback = User.objects.filter(id=peer).first()
            record['user_name'] = user_display_name(fallback) or 'User'
            record['user_picture'] = first_media_url(
                getattr(fallback, 'profile_picture', None)
            )
    else:
        peer_user = User.objects.filter(id=peer).first()
        record['user_picture'] = (
            first_media_url(getattr(peer_user, 'profile_picture', None))
            if peer_user
            else None
        )
        record['user_name'] = user_display_name(peer_user) or 'User'
    return attach_listing_payload(record, peer_user_id=peer)


def serialize_listing_for_chat(listing) -> dict:
    '''Slim listing DTO for chat header cards (title · location, price · status).'''
    price = getattr(listing, 'price', None)
    price_label = None
    if price is not None and str(price).strip() != '':
        try:
            numeric = float(price)
            if numeric == int(numeric):
                price_label = f'${int(numeric)}'
            else:
                price_label = f'${numeric:.2f}'
        except (TypeError, ValueError):
            price_label = f'${price}'
        category = (getattr(listing, 'category', None) or '').strip().lower()
        if category in {'services', 'service'}:
            price_label = f'{price_label} per visit'

    pictures = getattr(listing, 'pictures', None) or []
    is_active = bool(getattr(listing, 'is_active', True))
    return {
        'id': str(getattr(listing, 'listing_id', '') or ''),
        'title': getattr(listing, 'title', None) or '',
        'location': getattr(listing, 'location', None) or '',
        'price': str(price) if price is not None else None,
        'price_label': price_label,
        'is_active': is_active,
        'status': 'Active' if is_active else 'Inactive',
        'picture': first_media_url(pictures),
        'category': getattr(listing, 'category', None) or '',
        'subcategory': getattr(listing, 'subcategory', None) or '',
    }


def resolve_listsync(listing_id):
    '''Fetch ListSync by listing ObjectId string.'''
    text = str(listing_id or '').strip()
    if not text:
        return None
    try:
        from bson import ObjectId
        from bson.errors import InvalidId
        from helpers.models import ListSync
    except ImportError:
        return None
    try:
        oid = ObjectId(text)
    except (InvalidId, TypeError, ValueError):
        return None
    try:
        return ListSync.objects.filter(listing_id=oid).first()
    except Exception:
        logger.exception('resolve_listsync failed for %s', text)
        return None


def _listsync_for_user(user_id):
    '''Most recent active listing for a user, else any listing.'''
    text = normalize_user_id(user_id)
    if not text:
        return None
    try:
        from helpers.models import ListSync

        uid = int(text)
    except (ImportError, TypeError, ValueError):
        return None
    try:
        doc = (
            ListSync.objects.filter(user_id=uid, is_active=True)
            .order_by('-created_at')
            .first()
        )
        if doc is not None:
            return doc
        return ListSync.objects.filter(user_id=uid).order_by('-created_at').first()
    except Exception:
        logger.exception('_listsync_for_user failed for %s', text)
        return None


def resolve_fallback_listing(record: dict, peer_user_id=None):
    '''
    When chat has no listing_id, pick a listing owned by the business-side
    participant (or peer / either participant) so inbox/header can show it.
    '''
    if not isinstance(record, dict):
        return None
    ordered_ids = []

    def _push(uid):
        text = normalize_user_id(uid)
        if text and text not in ordered_ids:
            ordered_ids.append(text)

    for role_key in ('receiver', 'sender'):
        role = record.get(role_key) or {}
        if str(role.get('user_type') or '').lower() == 'business':
            _push(role.get('user_id'))
    _push(peer_user_id)
    for participant in record.get('participants') or []:
        _push(participant)

    for uid in ordered_ids:
        doc = _listsync_for_user(uid)
        if doc is not None:
            return doc
    return None


def attach_listing_payload(record: dict, peer_user_id=None) -> dict:
    '''Attach nested ``listing`` for chat list / create / detail responses.'''
    if not isinstance(record, dict):
        return record
    listing_id = str(record.get('listing_id') or '').strip()
    listing_doc = resolve_listsync(listing_id) if listing_id else None
    if listing_doc is None:
        listing_doc = resolve_fallback_listing(record, peer_user_id)
        if listing_doc is not None:
            resolved_id = str(getattr(listing_doc, 'listing_id', '') or '')
            if resolved_id:
                record['listing_id'] = resolved_id
                # Persist so later list/detail calls stay stable.
                chat_id = str(record.get('chat_id') or '').strip()
                if chat_id:
                    try:
                        Chat.objects.filter(chat_id=chat_id).update(
                            set__listing_id=resolved_id
                        )
                    except Exception:
                        logger.exception(
                            'Failed to persist listing_id on chat %s', chat_id
                        )
    if listing_doc is None:
        record.pop('listing', None)
        return record
    record['listing'] = serialize_listing_for_chat(listing_doc)
    record['listing_id'] = record['listing'].get('id') or str(
        record.get('listing_id') or ''
    )
    return record


def message_preview(message) -> str:
    content = str(getattr(message, 'content', None) or '').strip()
    if content:
        return content
    urls = list(getattr(message, 'media_urls', None) or [])
    single = getattr(message, 'media_url', None)
    count = len(urls) if urls else (1 if single else 0)
    if count > 1:
        return f'{count} Photos'
    if count == 1:
        return 'Photo'
    return ''


def unread_count_for(chat, user_id) -> int:
    return Message.objects.filter(
        chat=chat, read=False, sender_id__ne=normalize_user_id(user_id)
    ).count()


def _message_media_urls(message) -> list:
    urls = [
        str(item).strip()
        for item in (getattr(message, 'media_urls', None) or [])
        if str(item or '').strip()
    ]
    if urls:
        return urls
    single = str(getattr(message, 'media_url', None) or '').strip()
    return [single] if single else []


def message_ws_payload(message, chat=None) -> dict:
    chat = chat or getattr(message, 'chat', None)
    chat_id = getattr(chat, 'chat_id', None) if chat is not None else None
    media_urls = _message_media_urls(message)
    return {
        'type': 'message',
        'id': str(getattr(message, 'id', '') or ''),
        'sender_id': str(getattr(message, 'sender_id', '') or ''),
        'content': message.content or '',
        'created_at': _isoformat(getattr(message, 'created_at', None)),
        'read': bool(getattr(message, 'read', False)),
        'media_url': media_urls[0] if media_urls else None,
        'media_urls': media_urls,
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
    sender_norm = normalize_user_id(sender_id)
    for uid in {sender_norm, normalize_user_id(peer_id)}:
        if not uid:
            continue
        # Sender's unread stays 0 for their own outbound message.
        unread = 0 if uid == sender_norm else unread_count_for(chat, uid)
        inbox = {
            'type': 'chat_updated',
            'chat_id': chat.chat_id,
            'last_message': preview,
            'message_created_at': created_at,
            'sender_id': str(sender_id),
            'unread_messages': unread,
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

