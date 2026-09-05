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
from users.serializers.business import BusinessSerailizer


class FetchBusinesses(generics.ListAPIView):
    '''
    Fetch all business from collection
    returns data in pagination format
    '''

    permission_classes = [IsAuthenticatedOrReadOnly, DenyAdminPathUnlessStaff]
    pagination_class = Pagination
    serializer_class = BusinessSerailizer

    def get_queryset(self):
        return Business.objects.all()


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


class FetchListings(generics.ListAPIView):
    '''
    Fetch user listings created from his business account.
    '''

    permission_classes = [IsAuthenticated, DenyAdminPathUnlessStaff]
    pagination_class = Pagination
    serializer_class = ListsyncSerializer

    def get_queryset(self):
        admin_path = '/admin-panel/'
        is_active = None
        if (
            self.request.path.startswith(admin_path)
            and self.request.user.is_superuser
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
            return queryset
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
            user_id = request.user.id
            business = Business.objects.get(user_id=user_id)
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
    API view that retrieves businesses located within a 10km radius of the specified location.
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
            'business_coordinates__near': [lon, lat],
            'business_coordinates__max_distance': 10000,  # 10km or 10000 meters
            'is_active': True,
        }

        if category != 'ALL' and category in CATEGORIES:
            search_business['business_category'] = category

        nearby_business = Business.objects.filter(**search_business)
        nearby_business_data = self.get_serializer(nearby_business, many=True)
        businesses = {item['id']: item for item in nearby_business_data.data}

        return response(
            status=status.HTTP_200_OK,
            message='Business Found Successfully',
            data=businesses,
        )
