'''Support ticket query helpers.'''

from datetime import datetime, timedelta

from django.utils import timezone
from django.utils.dateparse import parse_date


def day_bounds(value):
    if not value:
        return None, None
    if hasattr(value, 'year') and not isinstance(value, str):
        day = value
    else:
        day = parse_date(str(value).strip())
        if day is None:
            try:
                day = datetime.strptime(str(value).strip()[:10], '%Y-%m-%d').date()
            except (TypeError, ValueError):
                return None, None
    start = datetime(day.year, day.month, day.day)
    if timezone.is_aware(timezone.now()):
        start = timezone.make_aware(start, timezone.get_current_timezone())
    return start, start + timedelta(days=1)


def apply_support_filters(queryset, params):
    email = (params.get('search_email') or '').strip()
    request_status = (params.get('request_status') or '').strip()
    creation_date = (params.get('creation_date') or '').strip()

    if email:
        queryset = queryset.filter(email__icontains=email)
    if request_status and request_status.lower() not in ('all', '*'):
        queryset = queryset.filter(status=request_status)
    start, end = day_bounds(creation_date)
    if start is not None:
        queryset = queryset.filter(created_at__gte=start, created_at__lt=end)
    return queryset
