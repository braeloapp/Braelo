'''Admin report moderation rules. Warn does not ban on the first action.'''

from django.utils import timezone


def apply_user_moderation(user, action_type):
    '''Apply warn / ban / ignore to a user.

    First warn sets ``is_warned``. A later warn on an already-warned user
    escalates to a ban. Ban always deactivates the account.
    '''
    if action_type not in ('warn', 'ban', 'ignore'):
        raise ValueError('action_type must be warn, ban, or ignore')

    already_warned = bool(getattr(user, 'is_warned', False))
    banned = bool(getattr(user, 'is_banned', False))
    update_fields = []

    if action_type == 'ignore':
        return {
            'already_warned': already_warned,
            'banned': banned,
            'update_fields': update_fields,
        }

    if action_type == 'warn':
        if not already_warned:
            user.is_warned = True
            update_fields.append('is_warned')
        else:
            user.is_banned = True
            banned = True
            if 'is_banned' not in update_fields:
                update_fields.append('is_banned')
            if getattr(user, 'is_active', True):
                user.is_active = False
                update_fields.append('is_active')
    elif action_type == 'ban':
        user.is_banned = True
        banned = True
        update_fields.append('is_banned')
        if getattr(user, 'is_active', True):
            user.is_active = False
            update_fields.append('is_active')

    if hasattr(user, 'updated_at'):
        user.updated_at = timezone.now()
        update_fields.append('updated_at')
    return {
        'already_warned': already_warned,
        'banned': banned,
        'update_fields': list(dict.fromkeys(update_fields)),
    }
