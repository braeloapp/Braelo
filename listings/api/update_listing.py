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

from bson import ObjectId
from rest_framework import status
from mongoengine.errors import DoesNotExist
from rest_framework_mongoengine import generics
from rest_framework.permissions import IsAuthenticated
from users.permissions import DenyAdminPathUnlessStaff
from rest_framework.exceptions import ValidationError

from listings.models import (
    RealEstateListing,
    VehicleListing,
    ElectronicsListing,
    EventsListing,
    FashionListing,
    JobsListing,
    ServicesListing,
    SportsHobbyListing,
    KidsListing,
    FurnitureListing,
)
from helpers import response, handle_exceptions
from listings.field_contract import apply_field_aliases, extract_coordinates
from listings.serializers import (
    RealEstateUpdateSerializer,
    VehicleUpdateSerializer,
    ElectronicsUpdateSerializer,
    EventsUpdateSerializer,
    FashionUpdateSerializer,
    JobsUpdateSerializer,
    ServicesUpdateSerializer,
    SportsHobbyUpdateSerializer,
    KidsUpdateSerializer,
    FurnitureUpdateSerializer,
)


class UpdateListing(generics.UpdateAPIView):
    '''
    Base API endpoint to update a listing.
    '''

    permission_classes = [IsAuthenticated, DenyAdminPathUnlessStaff]

    @handle_exceptions
    def put(self, request, *args, **kwargs):
        '''
        PUT method to update a listing.
        :param request: request object. (dict)
        :return: updated listing status. (json)
        '''
        partial = kwargs.pop('partial', True)
        instance = self.get_object()
        mutable_data = request.data.copy()
        raw_coords = mutable_data.get('listing_coordinates')
        if raw_coords not in (None, ''):
            listing_coordinates = extract_coordinates(raw_coords)
            if listing_coordinates is None:
                raise ValidationError(
                    {
                        'listing_coordinates': (
                            'listing_coordinates must be a list with [longitude, latitude].'
                        )
                    }
                )
            mutable_data['listing_coordinates'] = listing_coordinates
        else:
            mutable_data.pop('listing_coordinates', None)
        mutable_data = apply_field_aliases(
            dict(mutable_data),
            subcategory=mutable_data.get('subcategory')
            or getattr(instance, 'subcategory', None),
        )
        serializer = self.get_serializer(
            instance,
            data=mutable_data,
            partial=partial,
            context={'request': request, 'is_update': True},
        )
        # Validate and update the listing if valid
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return response(
            status=status.HTTP_200_OK,
            message='Listing updated successfully',
            data=serializer.data,
        )

    def get_object(self):
        '''
        Override to fetch an object using a MongoDB ObjectId.
        '''
        pk = self.kwargs['pk']
        if not ObjectId.is_valid(pk):
            raise ValidationError({'pk': 'Invalid ObjectId format.'})
        try:
            return self.get_queryset().get(id=ObjectId(pk))
        except DoesNotExist:
            raise ValidationError({'detail': 'Listing not found.'})


class VehicleUpdateAPI(UpdateListing):
    '''
    API endpoint to update a new vehicle listings.
    '''

    serializer_class = VehicleUpdateSerializer

    def get_queryset(self):
        return VehicleListing.objects.all()


class RealEstateUpdateAPI(UpdateListing):
    '''
    API endpoint to update a new vehicle listings.
    '''

    serializer_class = RealEstateUpdateSerializer

    def get_queryset(self):
        return RealEstateListing.objects.all()


class ElectronicsUpdateAPI(UpdateListing):
    '''
    API endpoint to update a new vehicle listings.
    '''

    serializer_class = ElectronicsUpdateSerializer

    def get_queryset(self):
        return ElectronicsListing.objects.all()


class EventsUpdateAPI(UpdateListing):
    '''
    API endpoint to update a new vehicle listings.
    '''

    serializer_class = EventsUpdateSerializer

    def get_queryset(self):
        return EventsListing.objects.all()


class FashionUpdateAPI(UpdateListing):
    '''
    API endpoint to update a new vehicle listings.
    '''

    serializer_class = FashionUpdateSerializer

    def get_queryset(self):
        return FashionListing.objects.all()


class JobsUpdateAPI(UpdateListing):
    '''
    API endpoint to update a new vehicle listings.
    '''

    serializer_class = JobsUpdateSerializer

    def get_queryset(self):
        return JobsListing.objects.all()


class ServicesUpdateAPI(UpdateListing):
    '''
    API endpoint to update service-class listings.
    '''

    serializer_class = ServicesUpdateSerializer

    def get_queryset(self):
        return ServicesListing.objects.all()


class SportsHobbyUpdateAPI(UpdateListing):
    '''
    API endpoint to update a new vehicle listings.
    '''

    serializer_class = SportsHobbyUpdateSerializer

    def get_queryset(self):
        return SportsHobbyListing.objects.all()


class KidsUpdateAPI(UpdateListing):
    '''
    API endpoint to update a new vehicle listings.
    '''

    serializer_class = KidsUpdateSerializer

    def get_queryset(self):
        return KidsListing.objects.all()


class FurnitureUpdateAPI(UpdateListing):
    '''
    API endpoint to update a new vehicle listings.
    '''

    serializer_class = FurnitureUpdateSerializer

    def get_queryset(self):
        return FurnitureListing.objects.all()
