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
from helpers.normalize import resolve_category, resolve_subcategory
from helpers import upload_pictures
from helpers.notifications import business_created_event
from helpers import response, handle_exceptions
from admin_panel.models import AdminBusinessBanner
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

        deactivated_ids = []
        for business in active_businesses:
            business.is_active = False
            business.save(update_fields=['is_active'])
            set_businesses_directory_active(str(business.id), False)
            deactivated_ids.append(str(business.id))

        user.is_business = False
        user.save(update_fields=['is_business'])

        if request.path.startswith('/admin-panel/'):
            from admin_panel.services.audit import record_admin_action

            record_admin_action(
                actor=request.user,
                action='deactivate',
                target_type='business',
                target_id=deactivated_ids[0] if deactivated_ids else str(user_id),
                summary=f'Deactivated business for user {user_id}',
                previous_state={'is_active': True, 'is_business': True},
                new_state={
                    'is_active': False,
                    'is_business': False,
                    'business_ids': deactivated_ids,
                },
            )

        return response(
            status=status.HTTP_204_NO_CONTENT,
            message='Business Deactivated Successfully',
            data={'user_business_status': user.is_business},
        )


class AdminActivateBusiness(generics.CreateAPIView):
    '''
    Staff endpoint to reactivate a business that was deactivated from admin.
    Does not replace the app's self-serve Activate_Business.
    '''

    permission_classes = [IsAuthenticated, DenyAdminPathUnlessStaff]

    @handle_exceptions
    def post(self, request):
        user_id = request.data.get('user_id')
        if not user_id:
            raise ValidationError(
                {'field': 'user_id is required for admin path'}
            )
        user = User.objects.filter(id=user_id).first()
        if not user:
            raise ValidationError({'error': 'user not found'})

        candidates = [user.id, str(user.id)]
        try:
            candidates.append(int(user_id))
        except (TypeError, ValueError):
            candidates.append(user_id)
        candidates.append(str(user_id))
        seen = set()
        user_id_values = []
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            user_id_values.append(candidate)

        businesses = list(
            Business.objects(__raw__={'user_id': {'$in': user_id_values}})
        )
        if not businesses:
            raise ValidationError({'Business': 'Business not found'})

        inactive = [business for business in businesses if not business.is_active]
        if not inactive:
            raise ValidationError({'Business': 'Business is already active'})

        activated_ids = []
        for business in inactive:
            business.is_active = True
            business.save(update_fields=['is_active'])
            set_businesses_directory_active(str(business.id), True)
            upsert_businesses_directory_doc(business)
            activated_ids.append(str(business.id))

        user.is_business = True
        user.save(update_fields=['is_business'])

        from admin_panel.services.audit import record_admin_action

        record_admin_action(
            actor=request.user,
            action='activate',
            target_type='business',
            target_id=activated_ids[0] if activated_ids else str(user.id),
            summary=f'Reactivated business for user {user.id}',
            previous_state={'is_active': False, 'is_business': False},
            new_state={
                'is_active': True,
                'is_business': True,
                'business_ids': activated_ids,
            },
        )

        return response(
            status=status.HTTP_200_OK,
            message='Business reactivated successfully',
            data={
                'user_business_status': user.is_business,
                'business_ids': activated_ids,
            },
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
        admin_update = request.path.startswith('/admin-panel/business/update')
        # Admin edits send text fields only. Keep the stored logo, banner,
        # and gallery unless a new file is actually uploaded.
        if admin_update:
            partial = True
            if hasattr(mutable_data, '_mutable'):
                mutable_data._mutable = True
            for media_key in (
                'business_logo',
                'business_banner',
                'business_images',
            ):
                if media_key not in mutable_data:
                    continue
                if hasattr(mutable_data, 'getlist'):
                    files = [
                        item
                        for item in mutable_data.getlist(media_key)
                        if getattr(item, 'name', None)
                    ]
                else:
                    raw = mutable_data.get(media_key)
                    files = raw if isinstance(raw, list) else [raw]
                    files = [item for item in files if getattr(item, 'name', None)]
                mutable_data.pop(media_key, None)
                if files and hasattr(mutable_data, 'setlist'):
                    mutable_data.setlist(media_key, files)
                elif files:
                    mutable_data[media_key] = files
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
        category = (self.request.GET.get('category') or '').strip()
        try:
            if category:
                canonical_category = resolve_category(category)
                if canonical_category in CATEGORIES:
                    return AdminBusinessBanner.objects.filter(
                        business_category=canonical_category, is_active=True
                    )
            # Home / empty category must match the public Chrome response:
            # all active banners. Do not filter by user interests here —
            # interest tags (Cars, Motorcycle, …) do not match banner
            # categories (Vehicles, electronics, …), so logged-in clients
            # were getting an empty carousel.
            return AdminBusinessBanner.objects.filter(is_active=True)
        except Exception as exc:
            raise ValidationError({'Business': str(exc)})

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
        Admin banner update. Image, link, name, email, and category
        can all be changed. Matching fields on the linked Business
        profile are kept in sync.
        '''
        from django.utils import timezone

        instance = self.get_object()
        if hasattr(request.data, 'getlist'):
            files = [
                item
                for item in request.data.getlist('business_banner')
                if getattr(item, 'name', None)
            ]
        else:
            raw = request.data.get('business_banner')
            files = raw if isinstance(raw, list) else ([raw] if raw else [])
            files = [item for item in files if getattr(item, 'name', None)]

        url = request.data.get('url')
        if url in (None, ''):
            url = request.data.get('business_link')

        business_name = request.data.get('business_name')
        business_email = request.data.get('business_email')
        business_category = request.data.get('business_category')
        business_subcategory = request.data.get('business_subcategory')

        has_meta = any(
            value not in (None, '')
            for value in (
                business_name,
                business_email,
                business_category,
                business_subcategory,
            )
        )

        if not files and url in (None, '') and not has_meta:
            raise ValidationError(
                {
                    'error': (
                        'Provide a banner image, link, or at least one '
                        'field to update.'
                    )
                }
            )

        if files:
            updater = BusinessSerailizer()
            instance.business_banner = updater.update_media(
                list(instance.business_banner or []),
                instance.business_category,
                files,
                instance.user_id,
                image_type='business_banner',
            )
        if url not in (None, ''):
            instance.url = url
        if business_name not in (None, ''):
            instance.business_name = str(business_name).strip()
        if business_email not in (None, ''):
            instance.business_email = str(business_email).strip()
        if business_category not in (None, ''):
            canonical_category = resolve_category(business_category)
            instance.business_category = (
                canonical_category
                if canonical_category is not None
                else str(business_category).strip()
            )
        if business_subcategory not in (None, ''):
            canonical_sub = resolve_subcategory(
                instance.business_category, business_subcategory
            )
            instance.business_subcategory = (
                canonical_sub
                if canonical_sub is not None
                else str(business_subcategory).strip()
            )

        instance.updated_at = timezone.now()
        instance.save()

        # Keep the linked Business profile in sync with the banners tab.
        if instance.user_id:
            business = Business.objects.filter(user_id=instance.user_id).first()
            if business is not None:
                if instance.business_banner:
                    business.business_banner = list(instance.business_banner)
                if business_name not in (None, ''):
                    business.business_name = instance.business_name
                if business_email not in (None, ''):
                    business.business_email = instance.business_email
                if business_category not in (None, ''):
                    business.business_category = instance.business_category
                if business_subcategory not in (None, ''):
                    business.business_subcategory = instance.business_subcategory
                business.updated_at = timezone.now()
                business.save()

            # Keep every active banner for this business on the same name / email.
            sibling_updates = {}
            if business_name not in (None, ''):
                sibling_updates['business_name'] = instance.business_name
            if business_email not in (None, ''):
                sibling_updates['business_email'] = instance.business_email
            if sibling_updates:
                sibling_updates['updated_at'] = timezone.now()
                AdminBusinessBanner.objects.filter(
                    user_id=instance.user_id, is_active=True
                ).update(**sibling_updates)

        return response(
            status=status.HTTP_200_OK,
            message='Banner updated successfully',
            data=self.get_serializer(instance).data,
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
