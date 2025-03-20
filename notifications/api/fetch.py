'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
get notifications endpoints.
---------------------------------------------------
'''

from mongoengine.queryset import Q
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework_mongoengine import generics
from rest_framework import status


from notifications.models import Notification
from helpers import response
from notifications.serializers.fetch import NotificationSerializer


class Pagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50

    def get_paginated_response(self, data):
        paginated_data = super().get_paginated_response(data).data
        return response(
            status=status.HTTP_200_OK,
            message='notifications fetched Successfully',
            data=paginated_data,
        )


class FetchNotificationsAPI(generics.ListAPIView):
    '''
    API endpoint to fetch all notifications for the authenticated user.
    '''

    permission_classes = [IsAuthenticated]
    pagination_class = Pagination
    serializer_class = NotificationSerializer

    def get_queryset(self):
        user = self.request.user
        notifications = Notification.objects.filter(
            Q(type='admin') | Q(user_id=user.id)
        )

        return notifications
