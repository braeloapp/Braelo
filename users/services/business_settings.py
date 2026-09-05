'''
Business welcome-message and saved-reply persistence.

All operations are scoped to the authenticated user id.
'''

from rest_framework.exceptions import ValidationError

from users.models.business import Business
from users.models.business_settings import (
    BusinessSettings,
    SavedReply,
    new_reply_id,
    stamp_now,
)

MAX_SAVED_REPLIES = 20
MAX_MESSAGE_LEN = 2000
MAX_SHORTCUT_LEN = 80


def require_owned_business(user):
    business = Business.objects(user_id=user.id).first()
    if business is None:
        raise ValidationError({'Business': 'No business profile found'})
    return business


def get_or_create_settings(user_id):
    settings = BusinessSettings.objects(user_id=user_id).first()
    if settings is not None:
        return settings
    now = stamp_now()
    settings = BusinessSettings(
        user_id=user_id,
        welcome_message='',
        welcome_enabled=False,
        response_suggestions_enabled=False,
        saved_replies=[],
        created_at=now,
        updated_at=now,
    )
    settings.save()
    return settings


def _clean_text(value, field, required=False, max_len=MAX_MESSAGE_LEN):
    if value is None:
        text = ''
    else:
        text = str(value).strip()
    if required and not text:
        raise ValidationError({field: f'{field} is required'})
    if len(text) > max_len:
        raise ValidationError({field: f'{field} must be at most {max_len} characters'})
    return text


def update_settings(user, payload):
    require_owned_business(user)
    settings = get_or_create_settings(user.id)
    if 'welcome_message' in payload:
        settings.welcome_message = _clean_text(
            payload.get('welcome_message'),
            'welcome_message',
            required=False,
        )
    if 'welcome_enabled' in payload:
        settings.welcome_enabled = bool(payload.get('welcome_enabled'))
    if 'response_suggestions_enabled' in payload:
        settings.response_suggestions_enabled = bool(
            payload.get('response_suggestions_enabled')
        )
    settings.updated_at = stamp_now()
    settings.save()
    return settings


def add_saved_reply(user, shortcut, body):
    require_owned_business(user)
    settings = get_or_create_settings(user.id)
    if len(settings.saved_replies) >= MAX_SAVED_REPLIES:
        raise ValidationError(
            {'saved_replies': f'At most {MAX_SAVED_REPLIES} saved replies are allowed'}
        )
    shortcut = _clean_text(shortcut, 'shortcut', required=True, max_len=MAX_SHORTCUT_LEN)
    body = _clean_text(body, 'body', required=True)
    now = stamp_now()
    reply = SavedReply(
        reply_id=new_reply_id(),
        shortcut=shortcut,
        body=body,
        created_at=now,
        updated_at=now,
    )
    settings.saved_replies.append(reply)
    settings.updated_at = now
    settings.save()
    return settings, reply


def _find_reply(settings, reply_id):
    for reply in settings.saved_replies:
        if reply.reply_id == str(reply_id):
            return reply
    raise ValidationError({'reply_id': 'Saved reply not found'})


def update_saved_reply(user, reply_id, shortcut=None, body=None):
    require_owned_business(user)
    settings = get_or_create_settings(user.id)
    reply = _find_reply(settings, reply_id)
    if shortcut is not None:
        reply.shortcut = _clean_text(
            shortcut, 'shortcut', required=True, max_len=MAX_SHORTCUT_LEN
        )
    if body is not None:
        reply.body = _clean_text(body, 'body', required=True)
    reply.updated_at = stamp_now()
    settings.updated_at = reply.updated_at
    settings.save()
    return settings, reply


def delete_saved_reply(user, reply_id):
    require_owned_business(user)
    settings = get_or_create_settings(user.id)
    before = len(settings.saved_replies)
    settings.saved_replies = [
        reply
        for reply in settings.saved_replies
        if reply.reply_id != str(reply_id)
    ]
    if len(settings.saved_replies) == before:
        raise ValidationError({'reply_id': 'Saved reply not found'})
    settings.updated_at = stamp_now()
    settings.save()
    return settings


def maybe_send_business_welcome(chatroom, creator_id):
    '''
    If the non-creator participant is a business with welcome enabled,
    persist that welcome as the first message.
    '''
    from chats.models import Message
    from django.utils import timezone

    creator = str(creator_id)
    for participant in chatroom.participants or []:
        if str(participant) == creator:
            continue
        try:
            owner_id = int(participant)
        except (TypeError, ValueError):
            continue
        business = Business.objects(user_id=owner_id, is_active=True).first()
        if business is None:
            continue
        settings = BusinessSettings.objects(user_id=owner_id).first()
        if settings is None or not settings.welcome_enabled:
            continue
        body = (settings.welcome_message or '').strip()
        if not body:
            continue
        message = Message(
            chat=chatroom,
            sender_id=str(owner_id),
            content=body,
            read=False,
            created_at=timezone.now(),
        )
        message.save()
        return message
    return None
