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
)
from users.permissions import DenyAdminPathUnlessStaff
from rest_framework_simplejwt.authentication import JWTAuthentication

from users.models import User, Business
from helpers.constants import CATEGORIES
from helpers.normalize import resolve_category
from helpers import upload_pictures
from helpers.notifications import business_created_event
from helpers import response, handle_exceptions
from admin_panel.models import AdminBusinessBanner
from listings.api.fetch_listings import get_user_recommendations
from notifications.serializers.events import EventNotificationSerializer
from users.serializers.business import BusinessSerailizer, BannerSearilizer
from users.services.business_analytics import (
    build_business_dashboard,
    parse_period_days,
)
from users.services.businesses_directory_sync import (
    set_businesses_directory_active,
    upsert_businesses_directory_doc,
)


class BusinessPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50

    def get_paginated_response(self, data):
        filtered_data = [
            {
                'id': obj.get('id'),
                'business_banner': obj.get('business_banner', []),
                'business_id': obj.get('business_id'),
                'business_link': obj.get('business_link'),
            }
            for obj in data
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
    from django.conf import settings

    base_url = (getattr(settings, 'PUBLIC_BACKEND_URL', '') or '').rstrip('/')
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

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = BusinessSerailizer

    def get_queryset(self):
        return Business.objects.all()

    def send_notification(self, serialized_data):
        try:
            event_serializer = EventNotificationSerializer(
                data=business_created_event(
                    serialized_data['user_id'],
                    serialized_data['id'],
                    serialized_data.get('business_category') or '',
                )
            )
            event_serializer.is_valid(raise_exception=True)
            event_serializer.save()
            from notifications.services.email import email_service
            from notifications.services.preferences import is_preference_enabled
            from users.models import User

            owner_id = serialized_data['user_id']
            if is_preference_enabled(owner_id, 'business_created'):
                owner = User.objects.filter(id=owner_id).first()
                if owner and owner.email:
                    email_service.send_best_effort(
                        to=owner.email,
                        template_key='business_activated',
                        context={
                            'name': owner.name or owner.first_name or '',
                            'business_name': serialized_data.get('business_name')
                            or '',
                        },
                    )
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
        upsert_businesses_directory_doc(instance)
        serialized_data = BusinessSerailizer(instance).data
        self.send_notification(serialized_data)
        return response(
            status=status.HTTP_201_CREATED,
            message='Business created successfully',
            data=serialized_data,
        )


class DeactivateBusiness(generics.CreateAPIView):
    '''
    API endpoint to deactive a user
    '''

    permission_classes = [IsAuthenticated, DenyAdminPathUnlessStaff]

    @handle_exceptions
    def post(self, request):
        '''
        POST method to Deactivate business.
        :param request : reuqest object. (dict)
        :return: Deactivation Message. (json)
        '''
        admin_path = '/admin-panel/'
        if request.path.startswith(admin_path):
            user_id = request.data.get('user_id')
            if not user_id:
                raise ValidationError(
                    {'field': 'user_id is required for admin path'}
                )
            user = User.objects.filter(id=user_id).first()
            if not user:
                raise ValidationError({'error': 'user not found'})
        else:
            user = request.user
            user_id = user.id
            if not user.is_business:
                raise ValidationError({'user': 'User must be business_user'})

        active_businesses = list(
            Business.objects.filter(user_id=user_id, is_active=True)
        )
        if not active_businesses:
            raise ValidationError(
                {'Business': 'Business not found or already deactivated'}
            )

        for business in active_businesses:
            business.is_active = False
            business.save(update_fields=['is_active'])
            set_businesses_directory_active(str(business.id), False)

        user.is_business = False
        user.save(update_fields=['is_business'])
        return response(
            status=status.HTTP_204_NO_CONTENT,
            message='Business Deactivated Successfully',
            data={'user_business_status': user.is_business},
        )


class UpdateBusiness(generics.UpdateAPIView):
    '''
    Base API endpoint to update a listing.
    '''

    permission_classes = [IsAuthenticated, DenyAdminPathUnlessStaff]
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
        mutable_data = request.data.copy()
        raw_coordinates = request.data.get('business_coordinates')
        if raw_coordinates in (None, ''):
            existing = instance.business_coordinates
            if isinstance(existing, dict):
                mutable_data['business_coordinates'] = existing.get(
                    'coordinates', existing
                )
            else:
                mutable_data['business_coordinates'] = existing
        else:
            try:
                parsed_coordinates = (
                    json.loads(raw_coordinates)
                    if isinstance(raw_coordinates, str)
                    else raw_coordinates
                )
            except json.JSONDecodeError as exc:
                raise ValidationError(
                    'Invalid JSON format for business_coordinates.'
                ) from exc
            mutable_data['business_coordinates'] = parsed_coordinates
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
            try:
                user_id = int(user_id)
            except (TypeError, ValueError) as exc:
                raise ValidationError(
                    {'user_id': 'Must be a valid user id'}
                ) from exc
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
        upsert_businesses_directory_doc(business_status)

        return response(
            status=status.HTTP_201_CREATED,
            message='Business is now active',
            data={'user_status': user.is_business},
        )


class BusinessBanner(generics.ListCreateAPIView):
    '''
    Paginates business banners filtered by category or user interest.
    '''

    permission_classes = [AllowAny, DenyAdminPathUnlessStaff]
    pagination_class = BusinessPagination
    serializer_class = BannerSearilizer

    @handle_exceptions
    def post(self, request, *args, **kwargs):
        """
        Admin delete route is wired to this view.
        Some clients call it with POST instead of DELETE; support both.
        """
        admin_delete_path = '/admin-panel/business/banner/delete'
        if self.request.path.startswith(admin_delete_path):
            return self.delete(request)
        return super().post(request, *args, **kwargs)

    def get_queryset(self):
        user_id = self.request.user.id
        category = self.request.GET.get('category')
        try:
            if category:
                canonical_category = resolve_category(category)
                if canonical_category in CATEGORIES:
                    return AdminBusinessBanner.objects.filter(
                        business_category=canonical_category, is_active=True
                    )
            interests = get_user_recommendations(user_id)
            if not interests:
                return AdminBusinessBanner.objects.filter(is_active=True)
            queryset = AdminBusinessBanner.objects.filter(
                business_category=interests, is_active=True
            )
        except Exception as exc:
            raise ValidationError({'Business': str(exc)})
        return queryset

    @handle_exceptions
    def delete(self, request):
        admin_path = '/admin-panel/'
        if (
            self.request.path.startswith(admin_path)
            and self.request.user.is_superuser
        ):
            banner_id = request.data.get('banner_id')
            if not banner_id:
                raise ValidationError({'error': 'id is required'})

            deleted_count = AdminBusinessBanner.objects.filter(
                id=banner_id
            ).update(is_active=False)
            if deleted_count == 0:
                raise ValidationError(
                    {'error': 'Banner with the given id not found'}
                )
            return response(
                status=status.HTTP_204_NO_CONTENT,
                message='Banner Deleted Successfully',
                data={},
            )
        else:
            raise ValidationError(
                {
                    'error': 'Only admins are allowed to access this functionality.'
                }
            )

    @handle_exceptions
    def put(self, request, *args, **kwargs):
        '''
        PUT method to update a listing.
        :param request: request object. (dict)
        :return: updated listing status. (json)
        '''
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(
            instance,
            data=request.data,
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
        admin_path = '/admin-panel/business/banner/update'
        if (
            self.request.path.startswith(admin_path)
            and self.request.user.is_superuser
        ):
            banner_id = self.request.data.get('banner_id')
            if not banner_id:
                raise ValidationError({'Admin': 'Must provide banner_id'})
        else:
            raise ValidationError({'error': 'Only Admin is Allowed'})
        try:
            return AdminBusinessBanner.objects.get(id=banner_id, is_active=True)
        except DoesNotExist:
            raise ValidationError({'detail': 'Banner not found.'})


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
        period_days = parse_period_days(request.query_params.get('period'))
        business_insights = build_business_dashboard(user, period_days)
        return response(
            status=status.HTTP_200_OK,
            message='Dashboard Fetched Successfully',
            data=business_insights,
        )
