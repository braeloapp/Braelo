'''Listing visibility helpers that honour user-level blocks.'''


def exclude_blocked_owners(queryset, request):
    '''Hide listings owned by users who have a block relationship with the caller.'''
    user = getattr(request, 'user', None)
    if user is None or getattr(user, 'is_authenticated', False) is not True:
        return queryset
    try:
        from chats.services import blocked_owner_ids_for_listings

        blocked_ids = blocked_owner_ids_for_listings(user.id)
    except Exception:
        return queryset
    if not blocked_ids:
        return queryset
    return queryset.filter(user_id__nin=blocked_ids)
