'''Structured notification event payloads.

Callers must not mutate these factories. Routing keys live in ``data``,
never in the English ``body`` string.
'''


def listing_saved_event(user_id, listing_id):
    listing = '' if listing_id is None else str(listing_id)
    return {
        'type': 'listing',
        'title': 'Listing saved',
        'body': 'A listing was saved.',
        'user_id': [user_id],
        'data': {
            'type': 'listing_saved',
            'entity_type': 'listing',
            'entity_id': listing,
            'action': 'open_saved',
            'listing_id': listing,
        },
    }


def listing_created_event(user_id, listing_id, category=''):
    listing = '' if listing_id is None else str(listing_id)
    return {
        'type': 'listing',
        'title': 'Listing created',
        'body': 'Your listing was created successfully.',
        'user_id': [user_id],
        'data': {
            'type': 'listing_created',
            'entity_type': 'listing',
            'entity_id': listing,
            'action': 'open_my_listings',
            'listing_id': listing,
            'category': '' if category is None else str(category),
            'user_id': '' if user_id is None else str(user_id),
        },
    }


def business_created_event(user_id, business_id, business_type=''):
    business = '' if business_id is None else str(business_id)
    return {
        'type': 'business',
        'title': 'Business created',
        'body': 'Your business profile is ready.',
        'user_id': [user_id],
        'data': {
            'type': 'business_created',
            'entity_type': 'business',
            'entity_id': business,
            'action': 'open_dashboard',
            'business_id': business,
            'business_type': '' if business_type is None else str(business_type),
            'user_id': '' if user_id is None else str(user_id),
        },
    }


def chat_message_event(user_id, chat_id, sender_id, message_id=''):
    room = '' if chat_id is None else str(chat_id)
    return {
        'type': 'chat',
        'title': 'New message received',
        'body': 'You got a new message',
        'user_id': [user_id],
        'data': {
            'type': 'new_message',
            'entity_type': 'chat',
            'entity_id': room,
            'action': 'open',
            'chat_id': room,
            'sender_id': '' if sender_id is None else str(sender_id),
            'message_id': '' if message_id is None else str(message_id),
        },
    }


# Legacy names kept as factories so existing imports do not share mutable dicts.
def SAVED_EVENT_DATA():
    return listing_saved_event(None, '')


def BUSSINESS_EVENT_DATA():
    return business_created_event(None, '')


def LISTINGS_EVENT_DATA():
    return listing_created_event(None, '')


def CHAT_NOTIFICATION():
    return chat_message_event(None, '', '')
