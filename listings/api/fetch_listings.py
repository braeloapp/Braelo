'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
Fetch User listings endpoints.
---------------------------------------------------
'''

from mongoengine import Q
from django.db import transaction
from mongoengine.errors import DoesNotExist
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from users.permissions import DenyAdminPathUnlessStaff, is_admin_path, is_staff_user

from helpers import ListSync
from helpers.model_map import MODEL_MAP
from helpers.normalize import resolve_category
from helpers.optional_jwt import OptionalJWTAuthentication
from listings.api.paginate_listing import Pagination
from listings.geo import request_geo_filter
from listings.visibility import exclude_blocked_owners
from listings.listing_read import (
    HydratedListsyncListMixin,
    serialize_listing,
    serialize_listsync_rows,
    serialize_saved_rows,
)
from listings.models import SavedItem
from helpers import handle_exceptions, response
from users.models import Interest, User
from rest_framework.exceptions import ValidationError
from listings.serializers import ListsyncSerializer


def _account_listing_payload(item):
    payload = dict(item)
    if payload.get('price') is not None:
        payload['price'] = str(payload['price'])
    return payload


def get_user_listings(collection, user_id, offset, limit, sort, is_active=None):
    '''
    Retrieves listings from given collection.
    :param collection: CMongo db collection name. (Dict)
    :param user_id: user id. (int)
    :param offset: records to skip. (int)
    :param limit: records to fetch from db. (int)
    :return:
    '''
    queryset = collection.objects.filter(user_id=user_id)

    if is_active is not None:
        value = is_active.lower()
        if value not in ['true', 'false']:
            raise ValidationError(
                {'error': 'Invalid value for is_active. Use true or false.'}
            )
        is_active = value == 'true'
        queryset = queryset.filter(is_active=is_active)

    queryset = queryset.order_by(sort).skip(offset).limit(limit)

    return list(queryset)


def get_user_recommendations(user_id):
    '''
    Retrieves user interests.
    :param user_id: user id information. (int)
    :return: users interests. (list)
    '''
    try:
        interest = Interest.objects.get(user_id=user_id)
        return interest.tags
    except Interest.DoesNotExist:
        return []


class SavedListing(generics.ListAPIView):
    '''
    Fetch User Saved listing.
    '''

    permission_classes = [IsAuthenticated, DenyAdminPathUnlessStaff]

    @handle_exceptions
    def get(self, request, *args, **kwargs):
        '''
        GET method to retrieve saved items for the user.
        :param request: request object. (dict)
        :return: saved items. (json)
        '''
        if is_admin_path(request) and is_staff_user(request.user):
            user_id = request.GET.get('user_id')
            if not user_id:
                raise ValidationError({'Error': 'Admin Must Provide user_id'})
        else:
            user_id = request.user.id

        sort = '-saved_at'

        # Fetch all listings for the user across all categories
        limit = int(request.query_params.get('limit', 10))
        offset = int(request.query_params.get('offset', 0))
        listings = get_user_listings(SavedItem, user_id, offset, limit, sort)
        saved_payloads = serialize_saved_rows(listings, request)
        saved_listings = {}
        for item in saved_payloads:
            key = str(item.get('listing_id') or item.get('id') or '')
            if key:
                saved_listings[key] = _account_listing_payload(item)

        return response(
            status=status.HTTP_200_OK,
            message='Saved items retrieved successfully',
            data=saved_listings,
        )


class UserListing(generics.CreateAPIView):
    '''
    Fetch User listed listing.
    '''

    permission_classes = [IsAuthenticated, DenyAdminPathUnlessStaff]

    @handle_exceptions
    def get(self, request):
        # Get the logged-in user's ID
        is_active = None
        if is_admin_path(request) and is_staff_user(request.user):
            user_id = request.GET.get('user_id')
            is_active = request.query_params.get('is_active')
            if not user_id:
                raise ValidationError({'Error': 'Admin Must Provide user_id'})
        else:
            user_id = request.user.id

        sort = '-created_at'

        # Fetch all listings for the user across all categories
        limit = int(request.query_params.get('limit', 10))
        offset = int(request.query_params.get('offset', 0))
        listings = get_user_listings(
            ListSync, user_id, offset, limit, sort, is_active
        )
        user_payloads = serialize_listsync_rows(listings, request)
        user_listings = {}
        for item in user_payloads:
            key = str(item.get('listing_id') or item.get('id') or '')
            if key:
                user_listings[key] = _account_listing_payload(item)

        return response(
            status=status.HTTP_200_OK,
            message='User listings retrieved successfully',
            data=user_listings,
        )


class LookupListing(generics.CreateAPIView):
    '''
    look up user listing based on id.
    Public read: guests can open listing detail without a token.
    Authenticated business click analytics still tracked when logged in.
    '''

    permission_classes = [IsAuthenticatedOrReadOnly]
    authentication_classes = [OptionalJWTAuthentication]

    @handle_exceptions
    def get(self, request, **kwargs):
        '''
        Get method to fetch listing by id.
        :param request: request object. (dict)
        :return: Listing object. (dict)
        '''
        try:
            user = request.user
            authenticated = bool(getattr(user, 'is_authenticated', False))
            category = request.GET.get('category')
            listing_id = request.GET.get('listing_id')
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

            # Fetch the corresponding model
            model = MODEL_MAP[category]

            listing = model.objects.get(id=listing_id)
            if listing.from_business and authenticated:
                # Don't add clicks if users clicks his own listings
                if listing.user_id != user.id:
                    with transaction.atomic():
                        update_user_clicks = User.objects.get(
                            id=listing.user_id
                        )
                        listsync_listing = ListSync.objects.get(
                            listing_id=listing_id
                        )
                        listing.listing_clicks += 1
                        listsync_listing.listing_clicks += 1
                        update_user_clicks.listings_clicks += 1
                        listing.save()
                        listsync_listing.save()
                        update_user_clicks.save()
                    from users.services.business_analytics import (
                        record_listing_view,
                    )

                    record_listing_view(
                        listing.user_id, user.id, listing_id
                    )

            listing_data = serialize_listing(listing, request)

            return response(
                status=status.HTTP_200_OK,
                message='Listing fetched successfully',
                data=listing_data,
            )
        except DoesNotExist:
            raise ValidationError({'Listings': 'No listings found'})

    def get_queryset(self):
        return super().get_queryset()


class Recent(HydratedListsyncListMixin, generics.ListAPIView):

    pagination_class = Pagination
    serializer_class = ListsyncSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    authentication_classes = [OptionalJWTAuthentication]

    def get_queryset(self):
        filters = {'is_active': True}
        filters.update(request_geo_filter(self.request))
        return exclude_blocked_owners(
            ListSync.objects.filter(**filters), self.request
        )


class Recommendations(HydratedListsyncListMixin, generics.ListAPIView):
    '''
    Nearby + interest-ranked listings.

    Active listings always. Optional geo radius when coordinates are sent.
    Authenticated users with saved interests are filtered to matching
    category or subcategory even when a location is supplied.
    '''

    pagination_class = Pagination
    serializer_class = ListsyncSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    authentication_classes = [OptionalJWTAuthentication]

    def get_queryset(self):
        user = self.request.user
        authenticated = bool(getattr(user, 'is_authenticated', False))
        interests = (
            get_user_recommendations(user.id) if authenticated else []
        )
        filters = {'is_active': True}
        filters.update(request_geo_filter(self.request))
        try:
            queryset = ListSync.objects.filter(**filters)
            if interests:
                queryset = queryset.filter(
                    Q(category__in=interests) | Q(subcategory__in=interests)
                )
        except Exception as exc:
            raise ValidationError({'Listsync': str(exc)})
        return exclude_blocked_owners(queryset, self.request)
