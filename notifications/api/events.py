'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
notifications for events (like, saved) endpoints.
---------------------------------------------------
'''

from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework_mongoengine import generics

from helpers import handle_exceptions, response
from notifications.serializers.events import EventNotificationSerializer


class EventNotificationAPI(generics.CreateAPIView):
    '''
    Staff-only event trigger. Product events call the serializer in-process.
    '''

    permission_classes = [IsAdminUser]
    serializer_class = EventNotificationSerializer

    @handle_exceptions
    def post(self, request, **kwargs):
        '''
        POST method to trigger event notifications.
        :param request: request object. (dict)
        :return: notification status. (json)
        '''
        serializer = self.get_serializer(
            data=request.data, context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return response(
            status=status.HTTP_201_CREATED,
            message='Event notification triggered successfully.',
            data=serializer.data,
        )
