'''
MongoDB collection names for admin tools (e.g. dashboard data browser).
'''

from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.views import APIView

from helpers import handle_exceptions, response


class AdminMongoCollections(APIView):
    '''
    GET /admin-panel/collections — list MongoDB collection names (staff only).
    '''

    permission_classes = [IsAdminUser]

    @handle_exceptions
    def get(self, request):
        try:
            from mongoengine.connection import get_db

            db = get_db()
            names = sorted(db.list_collection_names())
        except Exception as exc:
            return response(
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
                message='MongoDB unavailable',
                data=None,
                error=str(exc),
            )
        return response(
            status=status.HTTP_200_OK,
            message='OK',
            data={'collections': names},
        )
