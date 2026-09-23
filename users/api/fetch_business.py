'''
---------------------------------------------------
Project:        Braelo
Date:           Dec 20, 2024
Author:         Faizan
---------------------------------------------------

Description:
Fetch Business endpoints.
---------------------------------------------------
'''

import json
from rest_framework import status
from mongoengine.errors import DoesNotExist
from rest_framework_mongoengine import generics
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import (
    IsAuthenticated,
    AllowAny,
    IsAuthenticatedOrReadOnly,
)
from users.permissions import DenyAdminPathUnlessStaff

from users.models import Business
from helpers.constants import CATEGORIES
from helpers.normalize import resolve_category, is_all_token
from helpers import ListSync
from helpers import response, handle_exceptions
from listings.serializers import ListsyncSerializer
from listings.api.paginate_listing import Pagination
from listings.geo import geo_near_filter, parse_radius_meters
from listings.listing_read import HydratedListsyncListMixin
from users.serializers.business import BusinessSerailizer
from users.services.business_lookup import find_user_business


class FetchBusinesses(generics.ListAPIView):
    '''
    Fetch all business from collection
    returns data in pagination format
    '''

    permission_classes = [IsAuthenticatedOrReadOnly, DenyAdminPathUnlessStaff]
    pagination_class = Pagination
    serializer_class = BusinessSerailizer

    def get_queryset(self):
        from mongoengine.queryset.visitor import Q
        from admin_panel.services.support import day_bounds

        qs = Business.objects.all().order_by('-created_at')
        params = self.request.query_params
        search = (params.get('search') or params.get('search_query') or '').strip()
        is_active = (params.get('is_active') or '').strip().lower()
        category = (params.get('category') or '').strip()
        creation_date = (params.get('creation_date') or '').strip()

        if search:
            qs = qs.filter(
                Q(business_name__icontains=search)
                | Q(business_email__icontains=search)
                | Q(business_number__icontains=search)
            )
        if is_active in ('true', 'false', '1', '0'):
            qs = qs.filter(is_active=is_active in ('true', '1'))
        if category and category.lower() not in ('all', '*'):
            resolved = resolve_category(category)
            qs = qs.filter(business_category=resolved or category)
        start, end = day_bounds(creation_date)
        if start is not None:
            qs = qs.filter(created_at__gte=start, created_at__lt=end)
        return qs


class ScanBusinessQR(generics.ListAPIView):
    '''
    Get endpoint to fetch business data
    will work when QR is scanned
    '''

    permission_classes = [AllowAny]

    @handle_exceptions
    def get(self, request, **kwargs):
        '''
        GET method to trigger QR code.
        :param : Primary Key. (Int)
        :return: business data. (json)
        '''

        business_id = self.kwargs['pk']
        business_listing = (
            Business.objects(id=business_id)
            .only(
                'business_logo',
                'business_name',
                'business_address',
                'business_number',
                'business_images',
            )
            .first()
        )

        if not business_listing:
            raise ValidationError({'error': 'No Business Found'})

        business_data = business_listing.to_mongo().to_dict()
        business_data.pop('_id', None)
        business_data.pop('business_qr', None)

        return response(
            status=status.HTTP_200_OK,
            message='Business Found',
            data=business_data,
        )


class FetchListings(HydratedListsyncListMixin, generics.ListAPIView):
    '''
    Fetch user listings created from his business account.

    Returns full category documents (make/model/year/etc.), not ListSync
    card stubs — same shape as /listing/paginate/* used by admin listing tabs.
    '''

    permission_classes = [IsAuthenticated, DenyAdminPathUnlessStaff]
    pagination_class = Pagination
    serializer_class = ListsyncSerializer

    def get_queryset(self):
        admin_path = '/admin-panel/'
        is_active = None
        if self.request.path.startswith(admin_path) and (
            self.request.user.is_staff or self.request.user.is_superuser
        ):
            user_id = self.request.query_params.get('user_id')
            is_active = self.request.query_params.get('is_active')

            if not user_id:
                raise ValidationError({'Error': 'Admin Must Provide user_id'})
        else:
            user = self.request.user
            if not user.is_business:
                raise ValidationError('User must be business')
            user_id = user.id

        try:

            # Admin business detail should show every listing owned by this
            # user. ``from_business`` is a create-path flag and was hiding
            # legitimate personal listings attached to the same account.
            if self.request.path.startswith(admin_path):
                queryset = ListSync.objects.filter(user_id=user_id)
            else:
                queryset = ListSync.objects.filter(
                    user_id=user_id, from_business=True
                )
            if is_active:
                if is_active not in ('true', 'false'):
                    raise ValidationError(
                        {'is_active': 'Must be [true or false]'}
                    )

                is_active = is_active == 'true'
                queryset = queryset.filter(is_active=is_active)
            return queryset.order_by('-created_at')
        except Exception as exc:
            raise ValidationError(
                {'ListSync': f'Error retrieving data: {str(exc)}'}
            )


class FetchSingleBusiness(generics.ListAPIView):
    '''
    API view that fetches a uer's business
    '''

    permission_classes = [IsAuthenticated]
    serializer_class = BusinessSerailizer

    def get(self, request):
        try:
            user = request.user
            business = find_user_business(
                user.id, email=getattr(user, 'email', None)
            )
            if business is None:
                return response(
                    status=status.HTTP_204_NO_CONTENT,
                    message='Business Not Found',
                    data={},
                )
            business_data = self.get_serializer(business)
            return response(
                status=status.HTTP_200_OK,
                message='Business Fetched Successfully',
                data=business_data.data,
            )
        except DoesNotExist:
            return response(
                status=status.HTTP_204_NO_CONTENT,
                message='Business Not Found',
                data={},
            )


class ExploreBusiness(generics.ListAPIView):
    '''
    Explore businesses for the map / explore feed.

    Query params:
    - ``category`` (required): taxonomy key or ``ALL``
    - ``coordinates`` (required): JSON ``[longitude, latitude]`` (kept for
      client contract / future distance sort; not used to hide businesses
      unless ``radius`` is also sent)
    - ``radius`` (optional, meters): when present, limit to businesses near
      ``coordinates``; when omitted, return **all** matching active businesses
      in the database (category filter still applies)
    '''

    permission_classes = [AllowAny]
    serializer_class = BusinessSerailizer

    @handle_exceptions
    def get(self, request):
        try:
            category = request.GET.get('category')
            business_coordinates = request.GET.get('coordinates', '')
            if not category or not business_coordinates:
                raise ValidationError(
                    {
                        'Field missing': 'category and coordinates both are required'
                    }
                )
            coordinates = json.loads(business_coordinates)
        except json.JSONDecodeError as exc:
            raise ValidationError(
                'Invalid JSON format for coordinates.'
            ) from exc

        if is_all_token(category):
            category = 'ALL'
        else:
            canonical_category = resolve_category(category)
            if canonical_category is None:
                raise ValidationError(
                    {
                        'category': f'Must be one of {list(CATEGORIES.keys())} OR "(ALL, all)"'
                    }
                )
            category = canonical_category

        if not isinstance(coordinates, list) or len(coordinates) != 2:
            raise ValidationError(
                {
                    'business_coordinates': 'Must be a list with [longitude, latitude].'
                }
            )

        lon, lat = coordinates
        if not (
            isinstance(lon, (int, float)) and isinstance(lat, (int, float))
        ):
            raise ValidationError(
                {'coordinates': 'Longitude and latitude must be numbers.'}
            )

        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValidationError(
                {
                    'business_coordinates': 'Longitude must be between -180 and 180, latitude must be between -90 and 90.'
                }
            )

        search_business = {
            'is_active': True,
        }
        # Only apply geo when the client explicitly asks for a radius.
        # Default explore (coordinates + category=ALL) returns every active
        # business so newly added businesses are not hidden by the 10km filter.
        raw_radius = request.GET.get('radius')
        if raw_radius is not None and str(raw_radius).strip() != '':
            search_business.update(
                geo_near_filter(
                    lon,
                    lat,
                    parse_radius_meters(raw_radius),
                    field='business_coordinates',
                )
            )

        if category != 'ALL' and category in CATEGORIES:
            search_business['business_category'] = category

        nearby_business = Business.objects.filter(**search_business)
        nearby_business_data = self.get_serializer(nearby_business, many=True)
        # Return a list — dict-by-id collapsed rows that shared a missing/duplicate id.
        businesses = list(nearby_business_data.data)

        return response(
            status=status.HTTP_200_OK,
            message='Business Found Successfully',
            data=businesses,
        )
