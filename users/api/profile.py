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


from users.services.business_lookup import find_user_business


logger = logging.getLogger(__name__)


def _find_user_business(user_id, email=None):
    '''Backward-compatible alias for flip-status and related endpoints.'''
    return find_user_business(user_id, email=email)


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
        target = serializer.context.get('target_user')
        previous = {}
        if target is not None and is_admin_path(request):
            previous = {
                'name': target.name,
                'email': target.email,
                'phone_number': target.phone_number,
                'is_active': target.is_active,
            }
        updated_data = serializer.save()
        if is_admin_path(request) and target is not None:
            from admin_panel.services.audit import record_admin_action

            record_admin_action(
                actor=request.user,
                action='update',
                target_type='user',
                target_id=str(target.id),
                summary=f'Updated user profile {target.id}',
                previous_state=previous,
                new_state=updated_data if isinstance(updated_data, dict) else {},
            )
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

        previous = {'is_active': True}
        user.is_active = False
        user.updated_at = timezone.now()
        user.save()

        if is_admin_path(request):
            from admin_panel.services.audit import record_admin_action

            record_admin_action(
                actor=request.user,
                action='deactivate',
                target_type='user',
                target_id=str(user.id),
                summary=f'Deactivated user {user.id}',
                previous_state=previous,
                new_state={'is_active': False},
            )

        return response(
            status=status.HTTP_200_OK,
            message='Profile deactivated successfully',
            data={},
        )


class ReactivateUser(generics.CreateAPIView):
    '''Staff-only reactivation of a deactivated account.'''

    permission_classes = [IsAuthenticated, DenyAdminPathUnlessStaff]

    @handle_exceptions
    def post(self, request, *args, **kwargs):
        require_staff(request)
        user_id = request.data.get('user_id')
        if not user_id:
            raise ValidationError({'error': 'user_id is missing'})
        user = User.objects.filter(id=user_id).first()
        if not user:
            raise ValidationError({'error': 'user not found'})
        if user.is_banned:
            raise ValidationError(
                {'user': 'Banned accounts cannot be reactivated from here.'}
            )
        if user.is_active:
            raise ValidationError({'user': 'This profile is already active.'})

        user.is_active = True
        user.updated_at = timezone.now()
        user.save(update_fields=['is_active', 'updated_at'])

        from admin_panel.services.audit import record_admin_action

        record_admin_action(
            actor=request.user,
            action='activate',
            target_type='user',
            target_id=str(user.id),
            summary=f'Reactivated user {user.id}',
            previous_state={'is_active': False},
            new_state={'is_active': True},
        )
        return response(
            status=status.HTTP_200_OK,
            message='Profile reactivated successfully',
            data={'id': user.id, 'is_active': True},
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

        # Mongo is the source of truth. Lookup is tolerant of legacy user_id
        # type drift and can fall back to business_email.
        existing_business = _find_user_business(
            user_id, email=getattr(user, 'email', None)
        )

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

            # previous_business alone is not enough — Mongo business must exist.
            logger.info(
                'flip_status.no_business user_id=%s email=%s '
                'is_business=%s previous_business=%s',
                user_id,
                getattr(user, 'email', None),
                user.is_business,
                user.previous_business,
            )
            return response(
                status=status.HTTP_406_NOT_ACCEPTABLE,
                message='Please Create Business First',
                data={},
            )

        # Handle 'user' status cases
        if user_status == 'user' and not user.is_business:
            raise ValidationError({'User': 'User is already a Normal User'})

        # Flip user status (personal mode)
        user.is_business = False
        user.save(update_fields=['is_business'])
        return response(
            status=status.HTTP_201_CREATED,
            message='Flipped User Status Successfully',
            data={'user_status': user.is_business},
        )
