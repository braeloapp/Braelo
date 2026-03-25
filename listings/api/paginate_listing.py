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
from helpers.model_map import MODEL_MAP
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

    def get_queryset(self):
        '''
        filtering query based on subcategory
        '''
        category = getattr(self, 'category', None)
        subcategory = self.request.GET.get('subcategory')

        if not subcategory or subcategory in ('ALL', 'all'):
            return super().get_queryset()

        if subcategory not in CATEGORIES.get(category, []):
            raise ValidationError(
                {
                    'subcategory': f'subcategories should be {CATEGORIES[category]}'
                }
            )

        model = MODEL_MAP.get(category)
        return model.objects.filter(subcategory=subcategory)


class PaginateVehicle(QueryFilter):
    '''
    Endpoint to retrieve the latest vehicle listings with pagination.
    '''

    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = VehicleSerializer
    category = 'Vehicles'

    def get_queryset(self):
        return VehicleListing.objects.all()


class PaginateRealEstate(QueryFilter):
    '''
    Endpoint to retrieve the latest real estate listings with pagination.
    '''

    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = RealEstateSerializer
    category = 'Real Estate'

    def get_queryset(self):
        return RealEstateListing.objects.all()


class PaginateElectronics(QueryFilter):
    '''
    Endpoint to retrieve the latest electronics listings with pagination.
    '''

    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = ElectronicsSerializer
    category = 'Electronics'

    def get_queryset(self):
        return ElectronicsListing.objects.all()


class PaginateEvents(QueryFilter):
    '''
    Endpoint to retrieve the latest events listings with pagination.
    '''

    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = EventsSerializer
    category = 'Events'

    def get_queryset(self):
        return EventsListing.objects.all()


class PaginateFashion(QueryFilter):
    '''
    Endpoint to retrieve the latest fashion listings with pagination.
    '''

    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = FashionSerializer
    category = 'Fashion'

    def get_queryset(self):
        return FashionListing.objects.all()


class PaginateJobs(QueryFilter):
    '''
    Endpoint to retrieve the latest jobs listings with pagination.
    '''

    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = JobsSerializer
    category = 'Jobs'

    def get_queryset(self):
        return JobsListing.objects.all()


class PaginateServices(QueryFilter):
    '''
    Endpoint to retrieve the latest services listings with pagination.
    '''

    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = ServicesSerializer
    category = 'Services'

    def get_queryset(self):
        return ServicesListing.objects.all()


class PaginateSportsHobby(QueryFilter):
    '''
    Endpoint to retrieve the latest sports and hobby listings with pagination.
    '''

    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = SportsHobbySerializer
    category = 'Sports & Hobby'

    def get_queryset(self):
        return SportsHobbyListing.objects.all()


class PaginateKids(QueryFilter):
    '''
    Endpoint to retrieve the latest kids listings with pagination.
    '''

    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = KidsSerializer
    category = 'Kids'

    def get_queryset(self):
        return KidsListing.objects.all()


class PaginateFurniture(QueryFilter):
    '''
    Endpoint to retrieve the latest furniture listings with pagination.
    '''

    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = FurnitureSerializer
    category = 'Furniture'

    def get_queryset(self):
        return FurnitureListing.objects.all()
