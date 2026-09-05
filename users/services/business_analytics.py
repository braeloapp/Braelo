'''
Business and admin analytics aggregations.

Identity is never taken from the client. Callers pass the authenticated
user or staff-only admin context.
'''

import calendar
import logging
from datetime import timedelta

from django.db.models import F, Sum
from django.utils import timezone

from users.models import User

logger = logging.getLogger('users.analytics')

VIEW = 'view'
SAVE = 'save'
MESSAGE = 'message'
INQUIRY = 'inquiry'
ALLOWED_EVENTS = {VIEW, SAVE, MESSAGE, INQUIRY}
DEFAULT_PERIOD_DAYS = 90
MAX_PERIOD_DAYS = 365
SERIES_MONTHS = 7
ADMIN_GROWTH_MONTHS = 12


def parse_period_days(raw, default=DEFAULT_PERIOD_DAYS):
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return default
    if days < 1:
        return default
    return min(days, MAX_PERIOD_DAYS)


def month_bucket_start(when, months_back=0):
    year = when.year
    month = when.month - months_back
    while month <= 0:
        month += 12
        year -= 1
    return when.replace(
        year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0
    )


def month_label(when):
    return calendar.month_abbr[when.month]


def build_month_axis(now=None, count=SERIES_MONTHS):
    now = now or timezone.now()
    labels = []
    starts = []
    for offset in range(count - 1, -1, -1):
        start = month_bucket_start(now, offset)
        labels.append(month_label(start))
        starts.append(start)
    return labels, starts


def bucket_datetimes(datetimes, starts, now=None):
    now = now or timezone.now()
    counts = [0] * len(starts)
    for value in datetimes:
        if value is None:
            continue
        if timezone.is_naive(value):
            value = timezone.make_aware(value, timezone.get_current_timezone())
        for index, start in enumerate(starts):
            if index + 1 < len(starts):
                end = starts[index + 1]
            else:
                end = now + timedelta(days=1)
            if start <= value < end:
                counts[index] += 1
                break
    return counts


def percent_change(current, previous):
    current = int(current or 0)
    previous = int(previous or 0)
    if previous == 0:
        if current == 0:
            return 0.0
        return 100.0
    return round(((current - previous) / previous) * 100.0, 1)


def change_payload(current, previous):
    current = int(current or 0)
    previous = int(previous or 0)
    return {
        'previous': previous,
        'percent': percent_change(current, previous),
    }


def record_event(user_id, event_type, listing_id=None, actor_id=None):
    if event_type not in ALLOWED_EVENTS:
        return None
    try:
        owner_id = int(user_id)
    except (TypeError, ValueError):
        return None
    if actor_id is not None:
        try:
            actor_id = int(actor_id)
        except (TypeError, ValueError):
            actor_id = None
        if actor_id == owner_id:
            return None
    try:
        from users.models.analytics_event import BusinessAnalyticsEvent

        event = BusinessAnalyticsEvent(
            user_id=owner_id,
            event_type=event_type,
            listing_id=str(listing_id) if listing_id else None,
            actor_id=actor_id,
            created_at=timezone.now(),
        )
        event.save()
        return event
    except Exception:
        logger.exception('Failed to record analytics event %s for %s', event_type, user_id)
        return None


def increment_inquiries(user_id):
    try:
        owner_id = int(user_id)
    except (TypeError, ValueError):
        return
    User.objects.filter(id=owner_id).update(
        business_interactions=F('business_interactions') + 1
    )


def record_listing_view(owner_id, actor_id, listing_id):
    record_event(owner_id, VIEW, listing_id=listing_id, actor_id=actor_id)


def record_listing_save(listing_id, actor_id):
    try:
        from helpers.models import ListSync

        listing = ListSync.objects.filter(listing_id=listing_id).first()
        if listing is None or not listing.from_business:
            return
        record_event(
            listing.user_id,
            SAVE,
            listing_id=listing_id,
            actor_id=actor_id,
        )
    except Exception:
        logger.exception('Failed to record listing save analytics')


def record_inbound_message(recipient_id, actor_id=None):
    try:
        owner_id = int(recipient_id)
    except (TypeError, ValueError):
        return
    if not User.objects.filter(id=owner_id, is_business=True).exists():
        return
    record_event(owner_id, MESSAGE, actor_id=actor_id)


def record_new_inquiry(business_user_id, actor_id=None):
    try:
        owner_id = int(business_user_id)
    except (TypeError, ValueError):
        return
    if not User.objects.filter(id=owner_id, is_business=True).exists():
        return
    increment_inquiries(owner_id)
    record_event(owner_id, INQUIRY, actor_id=actor_id)


def _aware(value):
    if value is None:
        return None
    if timezone.is_naive(value):
        return timezone.make_aware(value, timezone.get_current_timezone())
    return value


def _in_range(value, start, end):
    value = _aware(value)
    if value is None:
        return False
    return start <= value < end


def _count_events(user_id, event_type, start, end):
    from users.models.analytics_event import BusinessAnalyticsEvent

    return BusinessAnalyticsEvent.objects.filter(
        user_id=user_id,
        event_type=event_type,
        created_at__gte=start,
        created_at__lt=end,
    ).count()


def _event_datetimes(user_id, event_type, start):
    from users.models.analytics_event import BusinessAnalyticsEvent

    return [
        event.created_at
        for event in BusinessAnalyticsEvent.objects.filter(
            user_id=user_id,
            event_type=event_type,
            created_at__gte=start,
        ).only('created_at')
    ]


def _business_listing_docs(user_id):
    from helpers.models import ListSync

    return list(ListSync.objects.filter(user_id=user_id, from_business=True))


def _inbound_message_datetimes(user_id):
    from chats.models import Chat, Message

    chats = Chat.objects.filter(participants=str(user_id))
    chat_ids = [chat.id for chat in chats]
    if not chat_ids:
        return []
    return [
        message.created_at
        for message in Message.objects.filter(
            chat__in=chat_ids,
            sender_id__ne=str(user_id),
        ).only('created_at')
    ]


def _save_datetimes(listing_ids):
    from listings.models import SavedItem

    if not listing_ids:
        return []
    return [
        item.saved_at or getattr(item, 'created_at', None)
        for item in SavedItem.objects.filter(listing_id__in=listing_ids).only(
            'saved_at'
        )
    ]


def _inquiry_chat_datetimes(user_id):
    from chats.models import Chat

    return [
        chat.created_at
        for chat in Chat.objects.filter(participants=str(user_id)).only('created_at')
    ]


def build_business_dashboard(user, period_days=DEFAULT_PERIOD_DAYS):
    now = timezone.now()
    period_days = parse_period_days(period_days)
    current_start = now - timedelta(days=period_days)
    previous_start = current_start - timedelta(days=period_days)
    series_start = month_bucket_start(now, SERIES_MONTHS - 1)
    labels, starts = build_month_axis(now, SERIES_MONTHS)

    listings = _business_listing_docs(user.id)
    listing_ids = [listing.listing_id for listing in listings]
    active_listings = sum(1 for listing in listings if listing.is_active)
    listing_created = [listing.created_at for listing in listings]
    inbound_messages = _inbound_message_datetimes(user.id)
    inquiry_times = _inquiry_chat_datetimes(user.id)
    save_times = _save_datetimes(listing_ids)
    view_times = _event_datetimes(user.id, VIEW, series_start)

    views_current = _count_events(user.id, VIEW, current_start, now)
    views_previous = _count_events(user.id, VIEW, previous_start, current_start)
    messages_current = sum(
        1 for value in inbound_messages if _in_range(value, current_start, now)
    )
    messages_previous = sum(
        1
        for value in inbound_messages
        if _in_range(value, previous_start, current_start)
    )
    listings_current = sum(
        1 for value in listing_created if _in_range(value, current_start, now)
    )
    listings_previous = sum(
        1
        for value in listing_created
        if _in_range(value, previous_start, current_start)
    )
    inquiries_current = sum(
        1 for value in inquiry_times if _in_range(value, current_start, now)
    )
    saves_total = len(save_times)
    messages_total = len(inbound_messages)
    inquiries_total = len(inquiry_times)

    clicks = int(user.listings_clicks or 0)
    featured = int(user.business_featured or 0)
    interactions = messages_total

    return {
        'Clicks': clicks,
        'Interactions': interactions,
        'Listing': active_listings,
        'Featured': featured,
        'active_listings': active_listings,
        'saves': saves_total,
        'messages': messages_total,
        'inquiries': inquiries_total,
        'period_days': period_days,
        'changes': {
            'Clicks': change_payload(views_current, views_previous),
            'Interactions': change_payload(messages_current, messages_previous),
            'Listing': change_payload(listings_current, listings_previous),
            'Featured': change_payload(featured, featured),
        },
        'period': {
            'views': views_current,
            'messages': messages_current,
            'listings_created': listings_current,
            'inquiries': inquiries_current,
        },
        'series': {
            'labels': labels,
            'views': bucket_datetimes(view_times, starts, now),
            'messages': bucket_datetimes(inbound_messages, starts, now),
            'listings': bucket_datetimes(listing_created, starts, now),
        },
    }


def _month_counts_from_datetimes(datetimes, starts, now):
    return bucket_datetimes(datetimes, starts, now)


def build_admin_statistics(months=ADMIN_GROWTH_MONTHS):
    from chats.models import Chat, Message
    from feedbacks.models import ReportMessage, Requests
    from helpers.models import ListSync
    from users.models.business import Business

    now = timezone.now()
    try:
        months = int(months)
    except (TypeError, ValueError):
        months = ADMIN_GROWTH_MONTHS
    months = max(3, min(months, 24))
    week_ago = now - timedelta(days=7)
    labels, starts = build_month_axis(now, months)
    series_start = starts[0]

    users_total = User.objects.count()
    users_active = User.objects.filter(is_active=True).count()
    users_new_7d = User.objects.filter(created_at__gte=week_ago).count()
    users_new_today = User.objects.filter(
        created_at__gte=now.replace(hour=0, minute=0, second=0, microsecond=0)
    ).count()

    businesses_total = Business.objects.count()
    businesses_active = Business.objects.filter(is_active=True).count()
    listings_total = ListSync.objects.count()
    listings_active = ListSync.objects.filter(is_active=True).count()

    by_category = {}
    for listing in ListSync.objects.only('category'):
        key = listing.category or 'unknown'
        by_category[key] = by_category.get(key, 0) + 1

    reports_total = ReportMessage.objects.count()
    support_total = Requests.objects.count()
    support_open = Requests.objects.filter(status='Active').count()
    messages_total = Message.objects.count()
    conversations_total = Chat.objects.count()
    listing_clicks = User.objects.aggregate(
        total=Sum('listings_clicks')
    ).get('total') or 0

    user_created = [
        user.created_at
        for user in User.objects.filter(created_at__gte=series_start).only(
            'created_at'
        )
    ]
    business_created = [
        business.created_at
        for business in Business.objects.filter(created_at__gte=series_start).only(
            'created_at'
        )
    ]
    listing_created = [
        listing.created_at
        for listing in ListSync.objects.filter(created_at__gte=series_start).only(
            'created_at'
        )
    ]

    recent_users = []
    for user in User.objects.filter(is_active=True).order_by('-id')[:8]:
        recent_users.append(
            {
                'id': user.id,
                'name': user.name or user.email or f'User {user.id}',
                'email': user.email,
                'city': user.city or '',
                'created_at': user.created_at.isoformat()
                if user.created_at
                else None,
            }
        )

    return {
        'users': {
            'total': users_total,
            'active': users_active,
            'new_7d': users_new_7d,
            'new_today': users_new_today,
        },
        'businesses': {
            'total': businesses_total,
            'active': businesses_active,
        },
        'listings': {
            'total': listings_total,
            'active': listings_active,
            'inactive': max(listings_total - listings_active, 0),
            'by_category': by_category,
        },
        'reports': {'total': reports_total},
        'support_requests': {
            'total': support_total,
            'open': support_open,
        },
        'messages': {
            'total': messages_total,
            'conversations': conversations_total,
        },
        'engagement': {'listing_clicks': int(listing_clicks)},
        'growth': {
            'labels': labels,
            'users': _month_counts_from_datetimes(user_created, starts, now),
            'businesses': _month_counts_from_datetimes(
                business_created, starts, now
            ),
            'listings': _month_counts_from_datetimes(
                listing_created, starts, now
            ),
        },
        'recent_active_users': recent_users,
    }
