'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
User saved listings endpoints.
---------------------------------------------------
'''

from django.db import transaction
from django.db.models import F
from users.models import User
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework_mongoengine import generics


from helpers.model_map import MODEL_MAP
from listings.models import SavedItem
from helpers.models import ListSync
from helpers.notifications import SAVED_EVENT_DATA
from listings.api.upsert_listing import Listing
from listings.serializers import SavedItemSerializer
from helpers.constants import USER_LISTINGS_THRESHOLD
from helpers import handle_exceptions, response, ListSynchronize
from helpers.normalize import resolve_category

from notifications.serializers.events import EventNotificationSerializer
from users.services.listings_directory_sync import (
    listing_source_for_model,
    remove_listing_directory_doc,
    upsert_listing_directory_doc,
)


class SaveListing(generics.CreateAPIView):
    '''
    Save user listed listing.
    '''

    permission_classes = [IsAuthenticated]
    serializer_class = SavedItemSerializer

    def get_queryset(self):
        return SavedItem.objects.all()

    def send_notification(self, request):
        SAVED_EVENT_DATA['data']['listing_id'] = request.data.get('listing_id')
        SAVED_EVENT_DATA['user_id'] = [request.user.id]
        try:
            event_serializer = EventNotificationSerializer(
                data=SAVED_EVENT_DATA
            )
            event_serializer.is_valid(raise_exception=True)
            event_serializer.save()
        except Exception:
            pass

    def create(self, request, *args, **kwargs):
        save_param = request.GET.get('save')

        if save_param is None or save_param not in ['True', 'False']:
            raise ValidationError(
                {'Correct Param Required': '"save" should be True or False'}
            )

        if save_param == 'True':
            serializer = self.get_serializer(
                data=request.data, context={'request': request}
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
            self.send_notification(request)

            return response(
                status=status.HTTP_201_CREATED,
                message='Listings Saved Successfully',
                data=serializer.data,
            )
        # Unsave functionality if PARAM is False
        req = request.data
        listing_id = req.get('listing_id')
        if not listing_id:
            raise ValidationError('listing_id is required.')
        deleted_count = SavedItem.objects.filter(listing_id=listing_id).delete()
        if deleted_count == 0:
            return response(
                status=status.HTTP_204_NO_CONTENT,
                message='No listing Found',
                data={},
            )

        return response(
            status=status.HTTP_200_OK,
            message='Deleted Listing successfully',
            data={},
        )


class FlipListingStatus(generics.CreateAPIView):
    '''
    Flip listing status.
    '''

    permission_classes = [IsAuthenticated]

    @handle_exceptions
    def post(self, request, **kwargs):
        req = request.data
        request_user_id = request.user.id
        listing_status = req.get('status')
        category = req.get('category')
        listing_id = req.get('listing_id')
        if not category or not listing_id:
            raise ValidationError(
                'Category and listing_id are required parameters.'
            )

        # Validate category (case/format-insensitive)
        canonical_category = resolve_category(category)
        if canonical_category is None or canonical_category not in MODEL_MAP:
            raise ValidationError(
                {
                    'category': f'Invalid category. Choose from {list(MODEL_MAP.keys())}.'
                }
            )
        category = canonical_category
        model = MODEL_MAP[category]
        listing_doc = model.objects.filter(id=listing_id).first()
        if not listing_doc:
            raise ValidationError(
                {
                    'Listings': (
                        'No listing found for this listing_id and category.'
                    )
                }
            )

        owner_user_id = listing_doc.user_id
        admin_path = '/admin-panel'
        admin = request.path.startswith(admin_path) and (
            request.user.is_staff or request.user.is_superuser
        )
        if not admin and owner_user_id != request_user_id:
            raise ValidationError(
                {
                    'Permission': (
                        'You can only flip listings that belong to your account.'
                    )
                }
            )

        listing_limit = User.objects.filter(id=owner_user_id).first()
        if not listing_limit:
            raise ValidationError({'User': 'Listing owner account not found.'})

        if (
            not admin
            and not listing_limit.is_business
            and listing_status
            and listing_limit.listings_count == USER_LISTINGS_THRESHOLD
        ):
            raise ValidationError(
                {'Listing Limit': 'Cannot Exceed 10 For Normal User'}
            )

        ListSynchronize.flip_status(
            listing_id=listing_id,
            status=listing_status,
            model=model,
            user_id=owner_user_id,
            admin=admin,
        )
        ListSynchronize.flip_status(
            listing_id=listing_id,
            status=listing_status,
            user_id=owner_user_id,
            admin=admin,
        )
        # Updates listings_count for the listing owner (not the admin acting user).
        if listing_status:
            listing_limit.listings_count += 1
        elif not listing_limit.is_business and listing_limit.listings_count > 0:
            listing_limit.listings_count -= 1
        listing_limit.save()

        updated_listing = model.objects.filter(id=listing_id).first()
        if updated_listing:
            upsert_listing_directory_doc(updated_listing)

        return response(
            status=status.HTTP_200_OK,
            message='Flipped listing status successfully',
            data={},
        )


class DeleteListing(generics.RetrieveDestroyAPIView):
    '''
    Deletes a listing from category and listsync collection.
    Admins can delete any listing, while regular users can only delete their own.
    '''

    permission_classes = [IsAuthenticated]

    @handle_exceptions
    def delete(self, request):
        user = request.user
        user_id = user.id
        admin_path = "/admin-panel"
        listing_id = request.data.get('listing_id')
        category = request.data.get('category')

        if not category or not listing_id:
            raise ValidationError(
                {
                    'Parameters': 'Category and listing_id are required parameters.'
                }
            )

        canonical_category = resolve_category(category)
        if canonical_category is None or canonical_category not in MODEL_MAP:
            raise ValidationError(
                {
                    'category': f'Invalid category. Choose from {list(MODEL_MAP.keys())}.'
                }
            )
        category = canonical_category

        # Check if the user is an admin
        admin = request.path.startswith(admin_path) and (
            user.is_staff or user.is_superuser
        )

        listing = MODEL_MAP[category].objects.filter(id=listing_id).first()
        if not listing:
            return response(
                status=status.HTTP_204_NO_CONTENT,
                message='No listing found in category collection',
                data={},
            )

        listing_owner_id = listing.user_id

        # Admin can delete any listing; regular users can only delete their own
        if not admin and listing_owner_id != user_id:
            raise ValidationError(
                {'Error': 'You cannot delete someone else listing'}
            )

        listing_src = listing_source_for_model(MODEL_MAP[category])
        with transaction.atomic():
            deleted_category_count = (
                MODEL_MAP[category].objects.filter(id=listing_id).delete()
            )
            deleted_listsync_count = ListSync.objects.filter(
                listing_id=listing_id
            ).delete()

            if deleted_category_count == 0 and deleted_listsync_count == 0:
                return response(
                    status=status.HTTP_204_NO_CONTENT,
                    message='No listing found in either category or listsync collection',
                    data={},
                )

            # Decrease the count for the original owner
            User.objects.filter(id=listing_owner_id, is_business=False).update(
                listings_count=F('listings_count') - 1
            )

        remove_listing_directory_doc(str(listing_id), listing_src)

        return response(
            status=status.HTTP_200_OK,
            message='Listing deleted successfully',
            data={},
        )
