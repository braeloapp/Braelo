'''Shared helpers for locating a user's Mongo Business document.'''

from __future__ import annotations


def find_user_business(user_id):
    '''
    Locate the Mongo ``Business`` doc for a user, defending against legacy
    rows where ``user_id`` was persisted as a string instead of int.

    Returns the most-recently-created match (active preferred) or ``None``.
    '''
    from users.models import Business

    candidates = [user_id]
    try:
        candidates.append(int(user_id))
    except (TypeError, ValueError):
        pass
    candidates.append(str(user_id))

    seen = set()
    user_id_values = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        user_id_values.append(candidate)

    return (
        Business.objects(__raw__={'user_id': {'$in': user_id_values}})
        .order_by('-is_active', '-created_at')
        .first()
    )
