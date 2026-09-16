'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
Populate Listing and save listings endpoints.
---------------------------------------------------
'''

from rest_framework import status
from rest_framework_mongoengine import generics
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from helpers.notifications import listing_created_event
from notifications.serializers.events import EventNotificationSerializer


from listings.models import (
    ElectronicsListing,
    EventsListing,
    FashionListing,
    JobsListing,
    ServicesListing,
    SportsHobbyListing,
    KidsListing,
    FurnitureListing,
    RealEstateListing,
    VehicleListing,
)
from helpers import response, handle_exceptions
from listings.field_contract import extract_coordinates
from listings.multipart_payload import (
    flatten_listing_request_data,
    normalize_keywords as _normalize_keywords,
)
from listings.serializers import (
    RealEstateSerializer,
    ElectronicsSerializer,
    EventsSerializer,
    FurnitureSerializer,
    FashionSerializer,
    JobsSerializer,
    ServicesSerializer,
    SportsHobbySerializer,
    KidsSerializer,
    VehicleSerializer,
)


def _listing_create_payload(request, listing_coordinates):
    '''
    Plain dict for DRF/mongo ListField: QueryDict + ListField mixes getlist()
    with indexed keys (keywords[0]) and breaks CharField children. Files stay
    on getlist('pictures').
    '''
    payload = flatten_listing_request_data(request, for_update=False)
    payload['listing_coordinates'] = listing_coordinates
    return payload


class Listing(generics.CreateAPIView):
    '''
    Base API endpoint to create a new listing for different categories.
    '''

    permission_classes = [IsAuthenticated]

    def send_notification(self, serializer):
        try:
            listing_id = serializer.data['id']
            category = serializer.data['category']
            user_id = serializer.data['user_id']
            event_serializer = EventNotificationSerializer(
                data=listing_created_event(user_id, listing_id, category)
            )
            event_serializer.is_valid(raise_exception=True)
            event_serializer.save()
            from notifications.services.email import email_service
            from notifications.services.preferences import is_preference_enabled
            from users.models import User

            if is_preference_enabled(user_id, 'listing_created'):
                owner = User.objects.filter(id=user_id).first()
                if owner and owner.email:
                    email_service.send_best_effort(
                        to=owner.email,
                        template_key='listing_created',
                        context={
                            'name': owner.name or owner.first_name or '',
                            'listing_title': serializer.data.get('title') or '',
                            'category': category,
                        },
                    )
        except Exception:
            pass

    @handle_exceptions
    def post(self, request, **kwargs):
        '''
        POST method to add a listing.
        :param request: request object. (dict)
        :return: listing status. (json)
        '''
        listing_coordinates = request.data.get('listing_coordinates')
        if not listing_coordinates:
            raise ValidationError(
                {'listing_coordinates': 'field is required'}
            )
        listing_coordinates = extract_coordinates(listing_coordinates)
        if listing_coordinates is None:
            raise ValidationError(
                {
                    'listing_coordinates': (
                        'listing_coordinates must be a list with [longitude, latitude].'
                    )
                }
            )
        payload = _listing_create_payload(request, listing_coordinates)
        serializer = self.get_serializer(
            data=payload, context={'request': request}
        )
        # Validate and create the listing if valid
        serializer.is_valid(raise_exception=True)
        serializer.save()
        self.send_notification(serializer)

        return response(
            status=status.HTTP_201_CREATED,
            message='Listing created successfully',
            data=serializer.data,
        )


class VehicleAPI(Listing):
    '''
    API endpoint to create a new vehicle listings.
    '''

    serializer_class = VehicleSerializer

    def get_queryset(self):
        return VehicleListing.objects.all()


class RealEstateAPI(Listing):
    '''
    API endpoint to create a new vehicle listings.
    '''

    serializer_class = RealEstateSerializer

    def get_queryset(self):
        return RealEstateListing.objects.all()


class ElectronicsAPI(Listing):
    '''
    API endpoint to create a new vehicle listings.
    '''

    serializer_class = ElectronicsSerializer

    def get_queryset(self):
        return ElectronicsListing.objects.all()


class EventsAPI(Listing):
    '''
    API endpoint to create a new vehicle listings.
    '''

    serializer_class = EventsSerializer

    def get_queryset(self):
        return EventsListing.objects.all()


class FashionAPI(Listing):
    '''
    API endpoint to create a new vehicle listings.
    '''

    serializer_class = FashionSerializer

    def get_queryset(self):
        return FashionListing.objects.all()


class JobsAPI(Listing):
    '''
    API endpoint to create a new vehicle listings.
    '''

    serializer_class = JobsSerializer

    def get_queryset(self):
        return JobsListing.objects.all()


class ServicesAPI(Listing):
    '''
    API endpoint to create service-class listings (ServicesListing).
    '''

    serializer_class = ServicesSerializer

    def get_queryset(self):
        return ServicesListing.objects.all()


class SportsHobbyAPI(Listing):
    '''
    API endpoint to create a new vehicle listings.
    '''

    serializer_class = SportsHobbySerializer

    def get_queryset(self):
        return SportsHobbyListing.objects.all()


class KidsAPI(Listing):
    '''
    API endpoint to create a new vehicle listings.
    '''

    serializer_class = KidsSerializer

    def get_queryset(self):
        return KidsListing.objects.all()


class FurnitureAPI(Listing):
    '''
    API endpoint to create a new vehicle listings.
    '''

    serializer_class = FurnitureSerializer

    def get_queryset(self):
        return FurnitureListing.objects.all()
