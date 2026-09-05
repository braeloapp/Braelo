'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Haseeb
---------------------------------------------------

Description:
Update profile api.
---------------------------------------------------
'''

import logging

from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated, AllowAny
from users.permissions import DenyAdminPathUnlessStaff, is_admin_path, require_staff
from rest_framework.exceptions import ValidationError

from users.models import User
from users.serializers import (
    UpdateProfileSerializer,
    UserProfileSerializer,
)
from helpers import handle_exceptions, response, ListSync
from users.models.business import Business


logger = logging.getLogger(__name__)


def _find_user_business(user_id):
    '''
    Locate the Mongo ``Business`` doc for a user, defending against legacy
    rows where ``user_id`` was persisted as a string instead of int.

    Returns the most-recently-created match (active preferred) or ``None``.
    '''
    candidates = [user_id]
    try:
        candidates.append(int(user_id))
    except (TypeError, ValueError):
        pass
    candidates.append(str(user_id))
    # de-dupe while preserving order
    seen = set()
    user_id_values = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        user_id_values.append(candidate)

    return (
        Business.objects(__raw__={'user_id': {'$in': user_id_values}})
        .order_by('-is_active', '-created_at')
        .first()
    )


class UpdateProfile(generics.CreateAPIView):
    '''
    Update name fields endpoint.
    '''

    serializer_class = UpdateProfileSerializer
    permission_classes = [IsAuthenticated, DenyAdminPathUnlessStaff]

    @handle_exceptions
    def post(self, request, *args, **kwargs):
        '''
        Handle the Profile Update mechanism.
        '''
        serializer = self.get_serializer(
            data=request.data, context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        updated_data = serializer.save()
        return response(
            status=status.HTTP_200_OK,
            message='Profile updated successfully',
            data=updated_data,
        )


class UserProfile(generics.CreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserProfileSerializer

    @handle_exceptions
    def get(self, request, *args, **kwargs):
        user = request.user
        serializer = self.get_serializer(user)
        return response(
            status=status.HTTP_200_OK,
            message='Profile retrieved successfully',
            data=serializer.data,  # Send serialized user data
        )


class AboutUser(generics.CreateAPIView):
    '''
    Retrieve and Display User Information.
    '''

    permission_classes = [IsAuthenticated]

    @handle_exceptions
    def get(self, request):
        user = request.user
        created_at = user.created_at
        created_at = created_at.strftime('%B %Y')

        user_data = {
            'Name': user.name,
            'Created_at': created_at,
        }
        return response(
            status=status.HTTP_200_OK,
            message='User information fetched successfully',
            data=user_data,
        )


class PublicProfile(generics.CreateAPIView):
    '''
    Get Public profile.
    '''

    permission_classes = [AllowAny]

    @handle_exceptions
    def get(self, request):
        if request.user.is_authenticated:
            user_id = request.user.id
        else:
            # Get user_id from the request data
            user_id = request.data.get('user_id')
        if not user_id:
            return response(
                status=status.HTTP_400_BAD_REQUEST,
                message='user_id is required',
                data={},
            )
        user = get_object_or_404(User, id=user_id)
        member_since = user.created_at.strftime('%b %Y')

        # Count the listings in ListSync associated with the user_id
        listing_count = ListSync.objects.filter(user_id=user_id).count()

        # Prepare the response data
        profile_data = {
            'listing_count': listing_count,
            'name': user.name,
            'member_since': member_since,
        }
        return response(
            status=status.HTTP_200_OK,
            message='User information fetched successfully',
            data=profile_data,
        )


class DeactivateUser(generics.CreateAPIView):

    permission_classes = [IsAuthenticated, DenyAdminPathUnlessStaff]

    @handle_exceptions
    def post(self, request, *args, **kwargs):
        '''
        Handle the profile deactivation mechanism, either for admin or non-admin.
        '''
        if is_admin_path(request):
            require_staff(request)
            user_id = request.data.get('user_id')
            if not user_id:
                raise ValidationError({'error': 'user_id is missing'})
            user = User.objects.filter(id=user_id).first()
            if not user:
                raise ValidationError({'error': 'user not found'})
        else:
            user = self.request.user

        if not user.is_active:
            raise ValidationError(
                {'user': 'This profile is already deactivated.'}
            )

        user.is_active = False
        user.updated_at = timezone.now()
        user.save()

        return response(
            status=status.HTTP_200_OK,
            message='Profile deactivated successfully',
            data={},
        )


class FlipUserStatus(generics.CreateAPIView):
    '''
    Flips normal user into business user
    '''

    permission_classes = [IsAuthenticated]

    @handle_exceptions
    def post(self, request):
        user = request.user
        user_id = user.id
        user_status = request.data.get('status')

        # Validate user_status
        if user_status not in ['user', 'business']:
            raise ValidationError(
                {'Status': 'Status must be either "user" or "business".'}
            )

        # Mongo is the source of truth. The lookup is tolerant of legacy
        # ``user_id`` values stored as strings (schema drift) so it stays in
        # sync with ``auth/business/fetch-single``.
        existing_business = _find_user_business(user_id)

        if existing_business is not None and not user.previous_business:
            # Self-heal: prior creation succeeded in Mongo but the SQL flag
            # was never persisted (e.g. partial failure / direct insert).
            user.previous_business = True
            user.save(update_fields=['previous_business'])

        if user_status == 'business':
            if existing_business is not None and existing_business.is_active:
                update_fields = []
                if not user.is_business:
                    user.is_business = True
                    update_fields.append('is_business')
                if update_fields:
                    user.save(update_fields=update_fields)
                return response(
                    status=status.HTTP_200_OK,
                    message='Business Already Exists for User',
                    data={'user_status': user.is_business},
                )

            if existing_business is not None and not existing_business.is_active:
                return response(
                    status=status.HTTP_409_CONFLICT,
                    message=(
                        'Business Already Exists for User. '
                        'Business is Deactivated, Please Activate.'
                    ),
                    data={},
                )

            if not user.previous_business:
                logger.info(
                    'flip_status.no_business user_id=%s is_business=%s previous_business=%s',
                    user_id,
                    user.is_business,
                    user.previous_business,
                )
                return response(
                    status=status.HTTP_406_NOT_ACCEPTABLE,
                    message='Please Create Business First',
                    data={},
                )
            if user.is_business:
                raise ValidationError(
                    {'User': 'User is already a Business User'}
                )

        # Handle 'user' status cases
        if user_status == 'user' and not user.is_business:
            raise ValidationError({'User': 'User is already a Normal User'})

        # Flip user status
        user.is_business = user_status == 'business'
        user.save()
        return response(
            status=status.HTTP_201_CREATED,
            message='Flipped User Status Successfully',
            data={'user_status': user.is_business},
        )
