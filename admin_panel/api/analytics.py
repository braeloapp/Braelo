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
    # custom
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


def daily_series(model, start, end, field='created_at'):
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
    for doc in queryset.filter(created_at__gte=start, created_at__lte=end).only(
        'created_at'
    ):
        when = doc.created_at
        if not when:
            continue
        if timezone.is_naive(when):
            when = timezone.make_aware(when, timezone.get_current_timezone())
        key = when.date().isoformat()
        buckets[key] = buckets.get(key, 0) + 1
    return [{'date': key, 'value': buckets[key]} for key in sorted(buckets.keys())]


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
        listings = ListSync.objects.aggregate(
            total=Count('id'),
            active=Count('id', filter=Q(is_active=True)),
            inactive=Count('id', filter=Q(is_active=False)),
            new_today=Count('id', filter=Q(created_at__gte=today)),
            new_7d=Count('id', filter=Q(created_at__gte=week_ago)),
            new_period=Count(
                'id', filter=Q(created_at__gte=start, created_at__lte=end)
            ),
        )
        businesses = Business.objects.aggregate(
            total=Count('id'),
            active=Count('id', filter=Q(is_active=True)),
            inactive=Count('id', filter=Q(is_active=False)),
            new_period=Count(
                'id', filter=Q(created_at__gte=start, created_at__lte=end)
            ),
        )

        reports_pending = ReportMessage.objects.filter(status='Pending').count()
        reports_resolved = ReportMessage.objects.filter(status='Resolved').count()
        reports_ignored = ReportMessage.objects.filter(status='Ignored').count()
        support_open = Requests.objects.filter(status='Active').count()
        support_progress = Requests.objects.filter(status='In Progress').count()
        support_resolved = Requests.objects.filter(status='Resolved').count()

        by_category = {
            (row['category'] or 'unknown'): row['c']
            for row in ListSync.objects.values('category').annotate(c=Count('id'))
        }

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
                    'total': int(listings['total'] or 0),
                    'active': int(listings['active'] or 0),
                    'inactive': int(listings['inactive'] or 0),
                    'new_today': int(listings['new_today'] or 0),
                    'new_7d': int(listings['new_7d'] or 0),
                    'new_period': int(listings['new_period'] or 0),
                },
                'businesses': {
                    'total': int(businesses['total'] or 0),
                    'active': int(businesses['active'] or 0),
                    'inactive': int(businesses['inactive'] or 0),
                    'new_period': int(businesses['new_period'] or 0),
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
                'users': daily_series(User, start, end),
                'listings': daily_series(ListSync, start, end),
                'businesses': daily_series(Business, start, end),
                'reports': mongo_daily_series(ReportMessage.objects, start, end),
                'support': mongo_daily_series(Requests.objects, start, end),
            },
            'listings_by_category': by_category,
        }
        return response(
            status=status.HTTP_200_OK,
            message='Analytics overview fetched',
            data=data,
        )
