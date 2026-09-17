'''
Period-aware platform analytics for the Admin Command Center.
All series are computed from live DB aggregates — never fabricated.
'''

from datetime import timedelta

from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework.permissions import IsAdminUser
from rest_framework.views import APIView
from rest_framework import status

from helpers import handle_exceptions, response
from users.models import User
from users.models.business import Business
from helpers.models import ListSync
from feedbacks.models import ReportMessage, Requests


PERIODS = {
    'today': 0,
    '7d': 7,
    '30d': 30,
    '90d': 90,
}


def resolve_range(params):
    now = timezone.now()
    period = (params.get('period') or '30d').strip().lower()
    if period == 'today':
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now, period
    if period in PERIODS and period != 'today':
        days = PERIODS[period]
        start = (now - timedelta(days=days)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return start, now, period
    start_raw = params.get('start')
    end_raw = params.get('end')
    try:
        start = timezone.datetime.fromisoformat(start_raw.replace('Z', '+00:00'))
        if timezone.is_naive(start):
            start = timezone.make_aware(start, timezone.get_current_timezone())
    except Exception:
        start = (now - timedelta(days=30)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        period = '30d'
    try:
        end = timezone.datetime.fromisoformat(end_raw.replace('Z', '+00:00'))
        if timezone.is_naive(end):
            end = timezone.make_aware(end, timezone.get_current_timezone())
    except Exception:
        end = now
    return start, end, period if period else 'custom'


def daily_series_sql(model, start, end, field='created_at'):
    rows = (
        model.objects.filter(**{f'{field}__gte': start, f'{field}__lte': end})
        .annotate(day=TruncDate(field))
        .values('day')
        .annotate(value=Count('id'))
        .order_by('day')
    )
    return [
        {
            'date': row['day'].isoformat() if row['day'] else None,
            'value': int(row['value'] or 0),
        }
        for row in rows
        if row['day'] is not None
    ]


def mongo_daily_series(queryset, start, end):
    '''Best-effort daily buckets for MongoEngine querysets with created_at.'''
    buckets = {}
    try:
        docs = queryset.filter(created_at__gte=start, created_at__lte=end).only(
            'created_at'
        )
    except Exception:
        return []
    for doc in docs:
        when = getattr(doc, 'created_at', None)
        if not when:
            continue
        if timezone.is_naive(when):
            when = timezone.make_aware(when, timezone.get_current_timezone())
        key = when.date().isoformat()
        buckets[key] = buckets.get(key, 0) + 1
    return [{'date': key, 'value': buckets[key]} for key in sorted(buckets.keys())]


def mongo_count(queryset):
    try:
        return int(queryset.count())
    except Exception:
        return 0


def listing_category_counts():
    by_category = {}
    try:
        pipeline = [{'$group': {'_id': '$category', 'c': {'$sum': 1}}}]
        for row in ListSync.objects.aggregate(*pipeline):
            key = row.get('_id') or 'unknown'
            by_category[str(key)] = int(row.get('c') or 0)
    except Exception:
        try:
            for doc in ListSync.objects.only('category'):
                key = getattr(doc, 'category', None) or 'unknown'
                by_category[key] = by_category.get(key, 0) + 1
        except Exception:
            pass
    return by_category


class AdminAnalyticsOverview(APIView):
    permission_classes = [IsAdminUser]

    @handle_exceptions
    def get(self, request):
        start, end, period = resolve_range(request.query_params)
        today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = timezone.now() - timedelta(days=7)

        users = User.objects.aggregate(
            total=Count('id'),
            active=Count('id', filter=Q(is_active=True)),
            inactive=Count('id', filter=Q(is_active=False)),
            new_today=Count('id', filter=Q(created_at__gte=today)),
            new_7d=Count('id', filter=Q(created_at__gte=week_ago)),
            new_period=Count(
                'id', filter=Q(created_at__gte=start, created_at__lte=end)
            ),
        )

        listings_total = mongo_count(ListSync.objects)
        listings_active = mongo_count(ListSync.objects.filter(is_active=True))
        listings_inactive = max(listings_total - listings_active, 0)
        listings_new_today = mongo_count(
            ListSync.objects.filter(created_at__gte=today)
        )
        listings_new_7d = mongo_count(
            ListSync.objects.filter(created_at__gte=week_ago)
        )
        listings_new_period = mongo_count(
            ListSync.objects.filter(created_at__gte=start, created_at__lte=end)
        )

        businesses_total = mongo_count(Business.objects)
        businesses_active = mongo_count(Business.objects.filter(is_active=True))
        businesses_inactive = max(businesses_total - businesses_active, 0)
        businesses_new_period = mongo_count(
            Business.objects.filter(created_at__gte=start, created_at__lte=end)
        )

        reports_pending = mongo_count(ReportMessage.objects.filter(status='Pending'))
        reports_resolved = mongo_count(
            ReportMessage.objects.filter(status='Resolved')
        )
        reports_ignored = mongo_count(ReportMessage.objects.filter(status='Ignored'))
        support_open = mongo_count(Requests.objects.filter(status='Active'))
        support_progress = mongo_count(
            Requests.objects.filter(status='In Progress')
        )
        support_resolved = mongo_count(Requests.objects.filter(status='Resolved'))

        data = {
            'period': period,
            'start': start.isoformat(),
            'end': end.isoformat(),
            'kpis': {
                'users': {
                    'total': int(users['total'] or 0),
                    'active': int(users['active'] or 0),
                    'inactive': int(users['inactive'] or 0),
                    'new_today': int(users['new_today'] or 0),
                    'new_7d': int(users['new_7d'] or 0),
                    'new_period': int(users['new_period'] or 0),
                },
                'listings': {
                    'total': listings_total,
                    'active': listings_active,
                    'inactive': listings_inactive,
                    'new_today': listings_new_today,
                    'new_7d': listings_new_7d,
                    'new_period': listings_new_period,
                },
                'businesses': {
                    'total': businesses_total,
                    'active': businesses_active,
                    'inactive': businesses_inactive,
                    'new_period': businesses_new_period,
                },
                'moderation': {
                    'pending_reports': reports_pending,
                    'resolved_reports': reports_resolved,
                    'ignored_reports': reports_ignored,
                },
                'support': {
                    'open': support_open,
                    'in_progress': support_progress,
                    'resolved': support_resolved,
                },
            },
            'series': {
                'users': daily_series_sql(User, start, end),
                'listings': mongo_daily_series(ListSync.objects, start, end),
                'businesses': mongo_daily_series(Business.objects, start, end),
                'reports': mongo_daily_series(ReportMessage.objects, start, end),
                'support': mongo_daily_series(Requests.objects, start, end),
            },
            'listings_by_category': listing_category_counts(),
            'drilldowns': {
                'users': '/pages/users',
                'listings': '/pages/listing',
                'businesses': '/pages/business',
                'reports': '/pages/reportedusers',
                'support': '/pages/support',
            },
        }
        return response(
            status=status.HTTP_200_OK,
            message='Analytics overview fetched',
            data=data,
        )
