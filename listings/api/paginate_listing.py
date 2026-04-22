'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
Pagination of Listing endpoints. ``category`` on each view must match a key
in ``helpers.constants.CATEGORIES``; ``model_class`` is the MongoEngine doc.
---------------------------------------------------
'''

from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.pagination import PageNumberPagination
from rest_framework.exceptions import ValidationError

from helpers import response
from helpers import CATEGORIES
from helpers.normalize import resolve_subcategory, is_all_token
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
    Subclasses set ``category`` (CATEGORIES key) and ``model_class`` (document).
    Optional ``?subcategory=`` filters by exact subcategory string.
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

        if not subcategory or is_all_token(subcategory):
            return qs

        canonical_subcategory = resolve_subcategory(category, subcategory)
        if canonical_subcategory is None:
            raise ValidationError(
                {
                    'subcategory': f'subcategories should be {CATEGORIES[category]}'
                }
            )

        return qs.filter(subcategory=canonical_subcategory)


class PaginateVehicle(QueryFilter):
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = VehicleSerializer
    category = 'Vehicles'
    model_class = VehicleListing


class PaginateRealEstate(QueryFilter):
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = RealEstateSerializer
    category = 'realestate'
    model_class = RealEstateListing


class PaginateElectronics(QueryFilter):
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = ElectronicsSerializer
    category = 'electronics'
    model_class = ElectronicsListing


class PaginateEvents(QueryFilter):
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = EventsSerializer
    category = 'events'
    model_class = EventsListing


class PaginateFashion(QueryFilter):
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = FashionSerializer
    category = 'fashion'
    model_class = FashionListing


class PaginateJobs(QueryFilter):
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = JobsSerializer
    category = 'jobs'
    model_class = JobsListing


class PaginateServices(QueryFilter):
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = ServicesSerializer
    category = 'Services'
    model_class = ServicesListing


class PaginateSportsHobby(QueryFilter):
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = SportsHobbySerializer
    category = 'sportsandhobby'
    model_class = SportsHobbyListing


class PaginateKids(QueryFilter):
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = KidsSerializer
    category = 'kids'
    model_class = KidsListing


class PaginateFurniture(QueryFilter):
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = FurnitureSerializer
    category = 'furniture'
    model_class = FurnitureListing
