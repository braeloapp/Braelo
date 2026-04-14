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

import json
from rest_framework import status
from rest_framework_mongoengine import generics
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from helpers.notifications import LISTINGS_EVENT_DATA
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


def _normalize_keywords(raw):
    '''
    Build a list[str] for ListField(StringField): split comma-separated text,
    strip accidental wrapping quotes (e.g. 'abc' from Postman), coerce non-strings.

    Multipart often sends one field value like "abc, used" → getlist may yield
    one string; we split commas inside each segment too.
    '''
    if raw is None:
        return []
    parts = []
    if isinstance(raw, (list, tuple)):
        for item in raw:
            s = str(item).strip()
            if not s:
                continue
            if (s.startswith("'") and s.endswith("'")) or (
                s.startswith('"') and s.endswith('"')
            ):
                s = s[1:-1].strip()
            if ',' in s:
                parts.extend([x.strip() for x in s.split(',') if x.strip()])
            else:
                parts.append(s)
    else:
        text = str(raw).strip()
        if not text:
            return []
        if (text.startswith("'") and text.endswith("'")) or (
            text.startswith('"') and text.endswith('"')
        ):
            text = text[1:-1].strip()
        parts = [s.strip() for s in text.split(',') if s.strip()]
    out = []
    for p in parts:
        s = str(p).strip()
        if len(s) >= 2 and (
            (s[0] == s[-1] == "'") or (s[0] == s[-1] == '"')
        ):
            s = s[1:-1].strip()
        if s:
            out.append(s)
    return out


def _listing_create_payload(request, listing_coordinates):
    '''
    Plain dict for DRF/mongo ListField: QueryDict + ListField mixes getlist()
    with indexed keys (keywords[0]) and breaks CharField children. Files stay
    on getlist('pictures').
    '''
    qd = request.data
    payload = {}
    for key in qd.keys():
        if key in ('pictures', 'keywords', 'listing_coordinates'):
            continue
        payload[key] = qd.get(key)
    payload['listing_coordinates'] = listing_coordinates
    file_list = request.FILES.getlist('pictures')
    if file_list:
        payload['pictures'] = file_list
    fb = payload.get('from_business')
    if isinstance(fb, str):
        payload['from_business'] = fb.strip().lower() in (
            'true',
            '1',
            'yes',
        )
    payload['keywords'] = _normalize_keywords(qd.get('keywords'))
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
            LISTINGS_EVENT_DATA['data']['listing_id'] = listing_id
            LISTINGS_EVENT_DATA['data']['category'] = category
            LISTINGS_EVENT_DATA['data']['user_id'] = user_id
            LISTINGS_EVENT_DATA['user_id'] = [user_id]
            event_serializer = EventNotificationSerializer(
                data=LISTINGS_EVENT_DATA
            )
            event_serializer.is_valid(raise_exception=True)
            event_serializer.save()
        except Exception:
            pass

    @handle_exceptions
    def post(self, request, **kwargs):
        '''
        POST method to add a listing.
        :param request: request object. (dict)
        :return: listing status. (json)
        '''
        try:
            listing_coordinates = request.data.get('listing_coordinates')
            if not listing_coordinates:
                raise ValidationError(
                    {'listing_coordinates': 'field is required'}
                )
            if isinstance(listing_coordinates, (dict, list)):
                coords_raw = listing_coordinates
            else:
                coords_raw = json.loads(listing_coordinates)
            if (
                isinstance(coords_raw, dict)
                and coords_raw.get('type') == 'Point'
                and isinstance(coords_raw.get('coordinates'), list)
                and len(coords_raw['coordinates']) >= 2
            ):
                listing_coordinates = [
                    float(coords_raw['coordinates'][0]),
                    float(coords_raw['coordinates'][1]),
                ]
            else:
                listing_coordinates = coords_raw
        except json.JSONDecodeError as exc:
            raise ValidationError(
                'Invalid JSON format for listing_coordinates.'
            ) from exc
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
    API endpoint to create a new vehicle listings.
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
