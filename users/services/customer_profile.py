'''
Customer account profile summary: listings, saved items, and views.
'''

from datetime import timedelta

from django.utils import timezone

from helpers.models import ListSync
from listings.models.saved_listing import SavedItem
from users.services.business_analytics import VIEW, _count_events
from users.services.user_payload import public_profile_picture


def _location_label(user):
    parts = [
        part.strip()
        for part in (user.city, user.state, user.country)
        if part and str(part).strip()
    ]
    return ', '.join(parts)


def _sum_listing_clicks(user_id):
    total = 0
    for doc in ListSync.objects.filter(user_id=user_id).only('listing_clicks'):
        total += int(getattr(doc, 'listing_clicks', 0) or 0)
    return total


def build_customer_profile(user):
    user_id = user.id
    listings_total = ListSync.objects.filter(user_id=user_id).count()
    listings_active = ListSync.objects.filter(
        user_id=user_id, is_active=True
    ).count()
    listings_pending = ListSync.objects.filter(
        user_id=user_id, is_active=False
    ).count()
    saved_listings = SavedItem.objects.filter(user_id=user_id).count()

    now = timezone.now()
    views_last_30d = _count_events(
        user_id, VIEW, now - timedelta(days=30), now
    )
    if not views_last_30d:
        views_last_30d = _sum_listing_clicks(user_id)

    created_at = user.created_at
    member_since = created_at.strftime('%b %Y') if created_at else ''

    return {
        'name': user.name or '',
        'profile_picture': public_profile_picture(user),
        'location': _location_label(user),
        'member_since': member_since,
        'is_phone_verified': bool(user.is_phone_verified),
        'is_business': bool(user.is_business),
        'listings': {
            'total': listings_total,
            'active': listings_active,
            'pending': listings_pending,
        },
        'saved': {
            'listings': saved_listings,
            'businesses': 0,
        },
        'views': {
            'last_30d': int(views_last_30d or 0),
        },
    }
