'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
Search of Listings endpoints.
---------------------------------------------------
'''

from mongoengine import Q
from rest_framework import generics, status
from rest_framework.permissions import (
    IsAuthenticatedOrReadOnly,
    IsAuthenticated,
)

from helpers import ListSync
from helpers.normalize import resolve_category, resolve_subcategory
from users.models.users import User
from helpers import handle_exceptions, response
from listings.api.paginate_listing import Pagination
from listings.geo import request_geo_filter
from listings.visibility import exclude_blocked_owners
from listings.serializers import ListsyncSerializer
from rest_framework.exceptions import ValidationError


MIN_SEARCH_LENGTH = 3


def _apply_taxonomy_filters(queryset, request):
    category_raw = (request.GET.get('category') or '').strip()
    subcategory_raw = (request.GET.get('subcategory') or '').strip()
    if not category_raw:
        if subcategory_raw:
            raise ValidationError(
                {'category': 'category is required when subcategory is set.'}
            )
        return queryset

    category = resolve_category(category_raw)
    if category is None:
        raise ValidationError({'category': 'Invalid category.'})
    queryset = queryset.filter(category=category)
    if not subcategory_raw:
        return queryset

    subcategory = resolve_subcategory(category, subcategory_raw)
    if subcategory is None:
        raise ValidationError({'subcategory': 'Invalid subcategory.'})
    return queryset.filter(subcategory=subcategory)


class Search(generics.ListAPIView):

    pagination_class = Pagination
    permission_classes = [IsAuthenticatedOrReadOnly]
    serializer_class = ListsyncSerializer

    def get_queryset(self):
        search = (self.request.GET.get('search') or '').strip()
        if len(search) < MIN_SEARCH_LENGTH:
            raise ValidationError(
                {'Search': f'At least {MIN_SEARCH_LENGTH} characters required'}
            )

        filters = {'is_active': True}
        filters.update(request_geo_filter(self.request))
        try:
            queryset = ListSync.objects.filter(**filters).filter(
                Q(title__icontains=search)
                | Q(category__icontains=search)
                | Q(subcategory__icontains=search)
                | Q(keywords__icontains=search)
                | Q(location__icontains=search)
            )
            queryset = _apply_taxonomy_filters(queryset, self.request)
            queryset = exclude_blocked_owners(queryset, self.request)
        except ValidationError:
            raise
        except Exception as exc:
            raise ValidationError({'Listsync': str(exc)}) from exc

        user = getattr(self.request, 'user', None)
        if user is not None and getattr(user, 'is_authenticated', False):
            db_user = User.objects.filter(id=user.id).first()
            if db_user is not None:
                recent = list(db_user.recent_searches or [])
                if not recent or recent[-1] != search:
                    if len(recent) >= 10:
                        recent.pop(0)
                    recent.append(search)
                    db_user.recent_searches = recent
                    db_user.save(update_fields=['recent_searches'])
        return queryset


class RecentSearches(generics.CreateAPIView):

    permission_classes = [IsAuthenticated]

    @handle_exceptions
    def get(self, request):
        user_id = request.user.id
        user = User.objects.filter(id=user_id).first()
        user_searches = user.recent_searches if user else []
        recent_searches = {
            i + 1: item for i, item in enumerate(user_searches)
        }  # convert to dict
        return response(
            status=status.HTTP_200_OK,
            message='Recent Searches Found',
            data=recent_searches,
        )


class DeleteSearches(generics.DestroyAPIView):

    permission_classes = [IsAuthenticated]

    @handle_exceptions
    def delete(self, request, *args, **kwargs):
        user_id = request.user.id
        user = User.objects.filter(id=user_id).first()
        if user:
            user.recent_searches.clear()
            user.save(update_fields=['recent_searches'])
        return response(
            status=status.HTTP_204_NO_CONTENT,
            message='Recent Searches Deleted',
            data=[],
        )
