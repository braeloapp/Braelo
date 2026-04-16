'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
Pagination of Listing endpoints.
---------------------------------------------------
'''

from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.pagination import PageNumberPagination
from rest_framework.exceptions import ValidationError


from helpers import response
from helpers import CATEGORIES
from listings.models import (
    VehicleListing,
    RealEstateListing,
    ElectronicsListing,
    EventsListing,
    FashionListing,
    JobsListing,
    ServicesListing,
    SportsHobbyListing,
    KidsListing,
    FurnitureListing,
)
from listings.serializers import (
    VehicleSerializer,
    RealEstateSerializer,
    ElectronicsSerializer,
    FashionSerializer,
    JobsSerializer,
    ServicesSerializer,
    SportsHobbySerializer,
    KidsSerializer,
    FurnitureSerializer,
    EventsSerializer,
)


class Pagination(PageNumberPagination):
    '''
    Listing pagination configurations.
    '''

    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50

    def get_paginated_response(self, data):
        paginated_data = super().get_paginated_response(data).data
        return response(
            status=status.HTTP_200_OK,
            message='listings fetched Successfully',
            data=paginated_data,
        )


class QueryFilter(generics.ListAPIView):
    '''
    Subclasses must set ``category`` (for CATEGORIES validation) and
    ``model_class`` (MongoEngine document for this listing type).

    Previously each subclass overrode ``get_queryset()`` with only
    ``Model.objects.all()``, which skipped subcategory filtering entirely.
    '''

    model_class = None

    def get_queryset(self):
        if self.model_class is None:
            raise ValidationError(
                {'configuration': 'Paginate view is missing model_class.'}
            )
        qs = self.model_class.objects.all()
        category = getattr(self, 'category', None)
        subcategory = self.request.GET.get('subcategory')

        if not category:
            return qs

        if not subcategory or subcategory in ('ALL', 'all'):
            return qs

        if subcategory not in CATEGORIES.get(category, []):
            raise ValidationError(
                {
                    'subcategory': f'subcategories should be {CATEGORIES[category]}'
                }
            )

        return qs.filter(subcategory=subcategory)


class PaginateVehicle(QueryFilter):
    '''
    Endpoint to retrieve the latest vehicle listings with pagination.
    '''

    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = VehicleSerializer
    category = 'Vehicles'
    model_class = VehicleListing


class PaginateRealEstate(QueryFilter):
    '''
    Endpoint to retrieve the latest real estate listings with pagination.
    '''

    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = RealEstateSerializer
    category = 'Real Estate'
    model_class = RealEstateListing


class PaginateElectronics(QueryFilter):
    '''
    Endpoint to retrieve the latest electronics listings with pagination.
    '''

    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = ElectronicsSerializer
    category = 'Electronics'
    model_class = ElectronicsListing


class PaginateEvents(QueryFilter):
    '''
    Endpoint to retrieve the latest events listings with pagination.
    '''

    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = EventsSerializer
    category = 'Events'
    model_class = EventsListing


class PaginateFashion(QueryFilter):
    '''
    Endpoint to retrieve the latest fashion listings with pagination.
    '''

    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = FashionSerializer
    category = 'Fashion'
    model_class = FashionListing


class PaginateJobs(QueryFilter):
    '''
    Endpoint to retrieve the latest jobs listings with pagination.
    '''

    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = JobsSerializer
    category = 'Jobs'
    model_class = JobsListing


class PaginateServices(QueryFilter):
    '''
    Endpoint to retrieve the latest services listings with pagination.
    '''

    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = ServicesSerializer
    category = 'Services'
    model_class = ServicesListing


class PaginateSportsHobby(QueryFilter):
    '''
    Endpoint to retrieve the latest sports and hobby listings with pagination.
    '''

    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = SportsHobbySerializer
    category = 'Sports & Hobby'
    model_class = SportsHobbyListing


class PaginateKids(QueryFilter):
    '''
    Endpoint to retrieve the latest kids listings with pagination.
    '''

    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = KidsSerializer
    category = 'Kids'
    model_class = KidsListing


class PaginateFurniture(QueryFilter):
    '''
    Endpoint to retrieve the latest furniture listings with pagination.
    '''

    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = FurnitureSerializer
    category = 'Furniture'
    model_class = FurnitureListing
