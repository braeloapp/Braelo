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
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser

from users.models import Interest
from users.serializers import InterestSerializer
from helpers import handle_exceptions, response, upload_pictures, validate_image
from users.services.user_payload import public_profile_picture


class InterestListCreateView(generics.ListCreateAPIView):
    '''
    User Interests interface.

    POST accepts JSON or multipart/form-data. Optional ``profile_picture``
    file uploads the user's avatar to Azure and saves ``User.profile_picture``.
    '''

    permission_classes = [IsAuthenticated]
    serializer_class = InterestSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        """Only the authenticated user's interests. Never return the full collection."""
        return Interest.objects.filter(user_id=self.request.user.id)

    @handle_exceptions
    def post(self, request, *args, **kwargs):
        '''
        Handle the POST request to create or update user interests.
        Optionally upload ``profile_picture`` in the same request.
        :param request: request object. (dict)
        :return: user's interest status. (json)
        '''
        data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
        data['user_id'] = request.user.id
        # Multipart may deliver tags as a single string; serializer handles it.
        if hasattr(data, 'getlist'):
            tags_list = data.getlist('tags')
            if len(tags_list) > 1:
                data['tags'] = tags_list
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)

        profile_url = None
        picture = request.FILES.get('profile_picture')
        if picture is not None:
            validate_image(picture, 'profile_picture')

        resp = serializer.save()
        if not resp:
            # todo: needs better logic
            raise Exception('Cannot Add interests to Database')

        if picture is not None:
            urls = upload_pictures(
                [picture],
                'user',
                request.user.id,
                image_type='profile',
            )
            profile_url = urls[0] if urls else None
            if profile_url:
                user = request.user
                user.profile_picture = profile_url
                user.save(update_fields=['profile_picture'])

        tags = serializer.validated_data.get('tags', [])
        out = {
            'user_id': request.user.id,
            'tags': tags,
        }
        if profile_url:
            out['profile_picture'] = profile_url
        else:
            pic = public_profile_picture(request.user)
            if pic:
                out['profile_picture'] = pic

        return response(
            status=status.HTTP_201_CREATED,
            message='Interests Added',
            data=out,
        )
