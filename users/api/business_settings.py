'''
Business settings and saved-reply APIs.
'''

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from helpers import handle_exceptions, response
from users.services.business_settings import (
    add_saved_reply,
    delete_saved_reply,
    get_or_create_settings,
    require_owned_business,
    update_saved_reply,
    update_settings,
)


class BusinessSettingsApi(APIView):
    permission_classes = [IsAuthenticated]

    @handle_exceptions
    def get(self, request):
        require_owned_business(request.user)
        settings = get_or_create_settings(request.user.id)
        return response(
            status=status.HTTP_200_OK,
            message='Business settings fetched successfully',
            data=settings.to_public_dict(),
        )

    @handle_exceptions
    def put(self, request):
        settings = update_settings(request.user, request.data or {})
        return response(
            status=status.HTTP_200_OK,
            message='Business settings updated successfully',
            data=settings.to_public_dict(),
        )


class BusinessSavedReplyListCreateApi(APIView):
    permission_classes = [IsAuthenticated]

    @handle_exceptions
    def get(self, request):
        require_owned_business(request.user)
        settings = get_or_create_settings(request.user.id)
        return response(
            status=status.HTTP_200_OK,
            message='Saved replies fetched successfully',
            data={'saved_replies': settings.to_public_dict()['saved_replies']},
        )

    @handle_exceptions
    def post(self, request):
        payload = request.data or {}
        settings, reply = add_saved_reply(
            request.user,
            payload.get('shortcut'),
            payload.get('body'),
        )
        return response(
            status=status.HTTP_201_CREATED,
            message='Saved reply created successfully',
            data={
                'reply': reply.to_public_dict(),
                'saved_replies': settings.to_public_dict()['saved_replies'],
            },
        )


class BusinessSavedReplyDetailApi(APIView):
    permission_classes = [IsAuthenticated]

    @handle_exceptions
    def put(self, request, reply_id):
        payload = request.data or {}
        settings, reply = update_saved_reply(
            request.user,
            reply_id,
            shortcut=payload.get('shortcut'),
            body=payload.get('body'),
        )
        return response(
            status=status.HTTP_200_OK,
            message='Saved reply updated successfully',
            data={
                'reply': reply.to_public_dict(),
                'saved_replies': settings.to_public_dict()['saved_replies'],
            },
        )

    @handle_exceptions
    def delete(self, request, reply_id):
        settings = delete_saved_reply(request.user, reply_id)
        return response(
            status=status.HTTP_200_OK,
            message='Saved reply deleted successfully',
            data={'saved_replies': settings.to_public_dict()['saved_replies']},
        )
