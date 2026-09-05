'''
Admin platform statistics.
'''

from rest_framework.permissions import IsAdminUser
from rest_framework.views import APIView
from rest_framework import status

from helpers import handle_exceptions, response
from users.services.business_analytics import build_admin_statistics


class AdminStatistics(APIView):
    permission_classes = [IsAdminUser]

    @handle_exceptions
    def get(self, request):
        data = build_admin_statistics(request.query_params.get('months'))
        return response(
            status=status.HTTP_200_OK,
            message='Statistics fetched successfully',
            data=data,
        )
