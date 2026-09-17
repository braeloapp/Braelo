'''Global admin search across users, businesses, and listings.'''

from django.db.models import Q
from rest_framework.permissions import IsAdminUser
from rest_framework.views import APIView
from rest_framework import status

from helpers import handle_exceptions, response
from users.models import User
from users.models.business import Business
from helpers.models import ListSync


class AdminGlobalSearch(APIView):
    permission_classes = [IsAdminUser]

    @handle_exceptions
    def get(self, request):
        q = (request.query_params.get('q') or '').strip()
        if len(q) < 2:
            return response(
                status=status.HTTP_400_BAD_REQUEST,
                message='Query must be at least 2 characters',
                data={'users': [], 'businesses': [], 'listings': []},
            )

        try:
            limit = min(max(int(request.query_params.get('limit', 8)), 1), 25)
        except (TypeError, ValueError):
            limit = 8

        users = []
        user_qs = User.objects.filter(
            Q(email__icontains=q)
            | Q(username__icontains=q)
            | Q(name__icontains=q)
            | Q(phone_number__icontains=q)
        ).order_by('-id')[:limit]
        for user in user_qs:
            users.append(
                {
                    'id': user.id,
                    'name': user.name or user.username or f'User {user.id}',
                    'email': user.email or '',
                    'phone': user.phone_number or '',
                    'is_active': bool(user.is_active),
                    'is_business': bool(getattr(user, 'is_business', False)),
                    'href': f'/pages/users/userdetail?id={user.id}',
                }
            )

        businesses = []
        try:
            biz_qs = Business.objects.filter(
                __raw__={
                    '$or': [
                        {'business_name': {'$regex': q, '$options': 'i'}},
                        {'business_email': {'$regex': q, '$options': 'i'}},
                        {'business_number': {'$regex': q, '$options': 'i'}},
                        {'business_address': {'$regex': q, '$options': 'i'}},
                    ]
                }
            )[:limit]
            for biz in biz_qs:
                businesses.append(
                    {
                        'id': str(biz.id),
                        'name': biz.business_name,
                        'email': biz.business_email or '',
                        'category': biz.business_category or '',
                        'city_hint': (biz.business_address or '')[:80],
                        'is_active': bool(biz.is_active),
                        'href': f'/pages/business/businessdetail?id={biz.id}',
                    }
                )
        except Exception:
            businesses = []

        listings = []
        try:
            listing_qs = ListSync.objects.filter(
                __raw__={
                    '$or': [
                        {'title': {'$regex': q, '$options': 'i'}},
                        {'category': {'$regex': q, '$options': 'i'}},
                        {'subcategory': {'$regex': q, '$options': 'i'}},
                    ]
                }
            )[:limit]
            for item in listing_qs:
                listings.append(
                    {
                        'id': str(item.id),
                        'title': item.title,
                        'category': item.category or '',
                        'subcategory': getattr(item, 'subcategory', '') or '',
                        'user_id': item.user_id,
                        'is_active': bool(getattr(item, 'is_active', True)),
                        'href': f'/pages/listing?category={item.category or ""}',
                    }
                )
        except Exception:
            listings = []

        return response(
            status=status.HTTP_200_OK,
            message='Search results',
            data={
                'q': q,
                'users': users,
                'businesses': businesses,
                'listings': listings,
            },
        )
