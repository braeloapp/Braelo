'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
User interests end-points module.
---------------------------------------------------
'''

from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated

from users.models import Interest
from users.serializers import InterestSerializer
from helpers import handle_exceptions, response


class InterestListCreateView(generics.ListCreateAPIView):
    '''
    User Interests interface.
    '''

    permission_classes = [IsAuthenticated]
    serializer_class = InterestSerializer

    def get_queryset(self):
        """Only the authenticated user's interests. Never return the full collection."""
        return Interest.objects.filter(user_id=self.request.user.id)

    @handle_exceptions
    def post(self, request, *args, **kwargs):
        '''
        Handle the POST request to create or update user interests.
        :param request: request object. (dict)
        :return: user's interest status. (json)
        '''
        data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
        data['user_id'] = request.user.id
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        resp = serializer.save()
        if not resp:
            # todo: needs better logic
            raise Exception('Cannot Add interests to Database')
        return response(
            status=status.HTTP_201_CREATED,
            message='Interests Added',
            data=data,
        )
