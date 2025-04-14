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
import qrcode
from io import BytesIO
from rest_framework import status
from mongoengine.errors import DoesNotExist
from rest_framework_mongoengine import generics
from rest_framework.pagination import PageNumberPagination
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import (
    IsAuthenticated,
    AllowAny,
    IsAuthenticatedOrReadOnly,
)

from users.models import User, Business
from helpers.constants import CATEGORIES
from helpers import ListSync, upload_pictures, BUSSINESS_EVENT_DATA
from helpers import response, handle_exceptions
from admin_panel.models import AdminBusinessBanner
from listings.serializers import ListsyncSerializer
from listings.api.paginate_listing import Pagination
from listings.api.fetch_listings import get_user_recommendations
from notifications.serializers.events import EventNotificationSerializer
from users.serializers.business import BusinessSerailizer, BannerSearilizer


class BusinessPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50

    def get_paginated_response(self, data):
        filtered_data = [
            {'business_banner': obj.get('business_banner', [])} for obj in data
        ]
        paginated_data = super().get_paginated_response(filtered_data).data
        return response(
            status=status.HTTP_200_OK,
            message='Business Banners fetched Successfully',
            data=paginated_data,
        )


def generate_QR(business_id, user_id, business_type):
    """
    Generate a QR code for the business URL, save it as PNG in-memory,
    upload it, and return the upload result plus the URL.
    """
    base_url = (
        'https://braelo-fug5gcb6c0hpbpdn.canadacentral-01.azurewebsites.net'
    )
    business_url = f'{base_url}/auth/business/{business_id}'

    img = qrcode.make(business_url)
    # Convert PIL Image to in-memory PNG
    picture = BytesIO()
    picture.name = f"{business_id}.png"
    img.save(picture, format='PNG')
    picture.seek(0)

    # Upload and return
    uploaded_image = upload_pictures(
        [picture], business_type, user_id, image_type='business_qr'
    )
    data = {
        'qr_image': uploaded_image,
        'unique_url': business_url,
    }
    return data


class BussinessListing(generics.CreateAPIView):
    '''
    API endpoint to handle business creation
    '''

    queryset = Business.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = BusinessSerailizer

    def send_notification(self, serialized_data):
        BUSSINESS_EVENT_DATA['data']['business_id'] = serialized_data['id']
        BUSSINESS_EVENT_DATA['data']['business_type'] = serialized_data[
            'business_category'
        ]
        BUSSINESS_EVENT_DATA['data']['user_id'] = serialized_data['user_id']
        BUSSINESS_EVENT_DATA['user_id'] = [serialized_data['user_id']]
        try:
            event_serializer = EventNotificationSerializer(
                data=BUSSINESS_EVENT_DATA
            )
            event_serializer.is_valid(raise_exception=True)
            event_serializer.save()
        except Exception:
            pass

    @handle_exceptions
    def post(self, request):
        '''
        POST method to Creates a business listing with a unique QR code and URL.
        :param request: request object. (dict)
        :return: Business listings data. (json)
        '''
        if Business.objects(user_id=request.user.id).first():
            raise ValidationError({'Business': 'Already exists for user'})

        try:
            business_coordinates = request.data.get('business_coordinates')
            business_coordinates = json.loads(business_coordinates)
        except json.JSONDecodeError as exc:
            raise ValidationError(
                'Invalid JSON format for business_coordinates.'
            ) from exc

        mutable_data = request.data.copy()
        mutable_data['business_coordinates'] = business_coordinates
        serializer = self.get_serializer(
            data=mutable_data, context={'request': request}
        )
        # Validate and create the listing if valid
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        business_qr = generate_QR(
            str(instance.id),
            instance.user_id,
            instance.business_category,
        )
        instance.business_qr = business_qr.get('qr_image')
        instance.business_url = business_qr.get('unique_url')
        instance.save()
        serialized_data = BusinessSerailizer(instance).data
        self.send_notification(serialized_data)
        return response(
            status=status.HTTP_201_CREATED,
            message='Business created successfully',
            data=serialized_data,
        )


class FetchBusinesses(generics.ListAPIView):
    '''
    Fetch all business from collection
    returns data in pagination format
    '''

    queryset = Business.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = BusinessSerailizer


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


class DeactivateBusiness(generics.CreateAPIView):
    '''
    API endpoint to deactive a user
    '''

    permission_classes = [IsAuthenticated]

    def post(self, request):
        '''
        POST method to Deactivate business.
        :param request : reuqest object. (dict)
        :return: Deactivation Message. (json)
        '''
        try:
            admin_path = '/admin-panel/'
            if request.path.startswith(admin_path):
                user_id = request.data.get('user_id')
                if not user_id:
                    raise ValidationError(
                        {'field': 'user_id is required for admin path'}
                    )
                user = User.objects.filter(id=user_id).first()
            else:
                user = request.user
                user_id = user.id
                if not user.is_business:
                    raise ValidationError(
                        {'user': 'User must be business_user'}
                    )

            business = Business.objects.get(user_id=user_id, is_active=True)
            business.is_active = False
            user.is_business = False
            user.save(update_fields=['is_business'])
            business.save(update_fields=['is_active'])
            return response(
                status=status.HTTP_204_NO_CONTENT,
                message='Business Deactivated Successfully',
                data={'user_business_status': user.is_business},
            )
        except DoesNotExist:
            raise ValidationError(
                {'Business': 'Business not found or already deactivated'}
            )


class FetchListings(generics.ListAPIView):
    '''
    Fetch user listings created from his business account.
    '''

    queryset = ListSync.objects.all()
    permission_classes = [IsAuthenticated]
    pagination_class = Pagination
    serializer_class = ListsyncSerializer

    def get_queryset(self):
        admin_path = '/admin-panel/'
        if (
            self.request.path.startswith(admin_path)
            and self.request.user.is_superuser
        ):
            user_id = self.request.query_params.get('user_id')
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
            return queryset
        except Exception as exc:
            raise ValidationError(
                {'ListSync': f'Error retrieving data: {str(exc)}'}
            )


class UpdateBusiness(generics.UpdateAPIView):
    '''
    Base API endpoint to update a listing.
    '''

    permission_classes = [IsAuthenticated]
    serializer_class = BusinessSerailizer

    @handle_exceptions
    def post(self, request, *args, **kwargs):
        '''
        PUT method to update a listing.
        :param request: request object. (dict)
        :return: updated listing status. (json)
        '''
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        try:
            business_coordinates = request.data.get('business_coordinates')
            business_coordinates = json.loads(business_coordinates)
        except json.JSONDecodeError as exc:
            raise ValidationError(
                'Invalid JSON format for business_coordinates.'
            ) from exc

        mutable_data = request.data.copy()
        mutable_data['business_coordinates'] = business_coordinates
        serializer = self.get_serializer(
            instance,
            data=mutable_data,
            partial=partial,
            context={'request': request},
        )
        # Validate and update the business if valid
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return response(
            status=status.HTTP_200_OK,
            message='Business updated successfully',
            data=serializer.data,
        )

    def get_object(self):
        '''
        Override to fetch an object using a MongoDB ObjectId.
        '''
        admin_path = '/admin-panel/business/update'
        if self.request.path.startswith(admin_path):
            user_id = self.request.data.get('user_id')
            if not user_id:
                raise ValidationError({'Admin': 'Must provide user_id'})
        else:
            user_id = self.request.user.id
        try:
            return Business.objects.get(user_id=user_id)
        except DoesNotExist:
            raise ValidationError({'detail': 'Business not found.'})


class Activate_Business(generics.UpdateAPIView):
    '''
    Business API endpoint to activate a business
    '''

    permission_classes = [IsAuthenticated]

    def post(self, request):
        '''
        POST method to Activate a Business.
        :return: Business Active Message
        '''

        user = request.user
        user_id = user.id
        business_status = Business.objects.filter(user_id=user_id).first()
        if business_status.is_active:
            raise ValidationError({'Business': 'Business is already active'})
        business_status.is_active = True
        user.is_business = True
        business_status.save()
        user.save()

        return response(
            status=status.HTTP_201_CREATED,
            message='Business is now active',
            data={'user_status': user.is_business},
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

        if category not in CATEGORIES and category not in ('ALL', 'all'):
            raise ValidationError(
                {
                    'category': f'Must be one of {list(CATEGORIES.keys())} OR "(ALL, all)"'
                }
            )

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

        if category in CATEGORIES:
            search_business['business_category'] = category

        nearby_business = Business.objects.filter(**search_business)
        nearby_business_data = self.get_serializer(nearby_business, many=True)
        businesses = {item['id']: item for item in nearby_business_data.data}

        return response(
            status=status.HTTP_200_OK,
            message='Business Found Successfully',
            data=businesses,
        )


class BusinessBanner(generics.ListAPIView):
    '''
    Paginates business banners filtered by category or user interest.
    '''

    permission_classes = [AllowAny]
    pagination_class = BusinessPagination
    serializer_class = BannerSearilizer

    def get_queryset(self):
        user_id = self.request.user.id
        category = self.request.GET.get('category')
        try:
            if category and category in CATEGORIES:
                return AdminBusinessBanner.objects.filter(
                    business_category=category
                )
            interests = get_user_recommendations(user_id)
            if not interests:
                return AdminBusinessBanner.objects.all()
            queryset = AdminBusinessBanner.objects.filter(
                business_category=interests
            )
        except Exception as exc:
            raise ValidationError({'Business': str(exc)})
        return queryset


class BusinessDashboard(generics.CreateAPIView):
    '''
    API endpoint to get business dashboard info based on user_id
    '''

    permission_classes = [IsAuthenticated]

    @handle_exceptions
    def get(self, request):
        '''
        GET method to fetch business dashboard.
        :return: business dashboard data.(json)
        '''
        user = request.user
        if not user.is_business:
            raise ValidationError({'User': 'Only Business Users Can Acesss'})
        business_insights = {
            'Clicks': user.listings_clicks,
            'Interactions': user.business_interactions,
            'Listing': user.listings_count,
            'Featured': user.business_featured,
        }
        return response(
            status=status.HTTP_200_OK,
            message='Dashboard Fetched Successfully',
            data=business_insights,
        )
