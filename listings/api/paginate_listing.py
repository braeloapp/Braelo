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

    queryset = VehicleListing.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = VehicleSerializer
    category = 'Vehicles'


class PaginateRealEstate(QueryFilter):
    '''
    Endpoint to retrieve the latest real estate listings with pagination.
    '''

    queryset = RealEstateListing.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = RealEstateSerializer
    category = 'Real Estate'


class PaginateElectronics(QueryFilter):
    '''
    Endpoint to retrieve the latest electronics listings with pagination.
    '''

    queryset = ElectronicsListing.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = ElectronicsSerializer
    category = 'Electronics'


class PaginateEvents(QueryFilter):
    '''
    Endpoint to retrieve the latest events listings with pagination.
    '''

    queryset = EventsListing.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = EventsSerializer
    category = 'Events'


class PaginateFashion(QueryFilter):
    '''
    Endpoint to retrieve the latest fashion listings with pagination.
    '''

    queryset = FashionListing.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = FashionSerializer
    category = 'Fashion'


class PaginateJobs(QueryFilter):
    '''
    Endpoint to retrieve the latest jobs listings with pagination.
    '''

    queryset = JobsListing.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = JobsSerializer
    category = 'Jobs'


class PaginateServices(QueryFilter):
    '''
    Endpoint to retrieve the latest services listings with pagination.
    '''

    queryset = ServicesListing.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = ServicesSerializer
    category = 'Services'


class PaginateSportsHobby(QueryFilter):
    '''
    Endpoint to retrieve the latest sports and hobby listings with pagination.
    '''

    queryset = SportsHobbyListing.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = SportsHobbySerializer
    category = 'Sports & Hobby'


class PaginateKids(QueryFilter):
    '''
    Endpoint to retrieve the latest kids listings with pagination.
    '''

    queryset = KidsListing.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = KidsSerializer
    category = 'Kids'


class PaginateFurniture(QueryFilter):
    '''
    Endpoint to retrieve the latest furniture listings with pagination.
    '''

    queryset = FurnitureListing.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = Pagination
    serializer_class = FurnitureSerializer
    category = 'Furniture'
