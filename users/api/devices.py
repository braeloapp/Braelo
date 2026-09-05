'''Device token registration and invalidation.'''

from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated

from helpers import handle_exceptions, response
from users.models.devices import UserDeviceToken
from users.serializers.devices import (
    DeleteDeviceTokenSerializer,
    DeviceTokenSerializer,
)


class SaveDeviceToken(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DeviceTokenSerializer

    @handle_exceptions
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            data=request.data, context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        device = serializer.save()
        return response(
            status=status.HTTP_201_CREATED,
            message='Device token Added successfully.',
            data={
                'platform': device.platform,
                'user_id': device.user_id,
            },
        )

    @handle_exceptions
    def delete(self, request, *args, **kwargs):
        payload = dict(request.data or {})
        if not payload.get('token'):
            payload['token'] = request.query_params.get('token') or ''
        serializer = DeleteDeviceTokenSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        token = (serializer.validated_data.get('token') or '').strip()
        query = UserDeviceToken.objects(user_id=request.user.id)
        if token:
            query = query.filter(token=token)
        deleted = query.delete()
        return response(
            status=status.HTTP_200_OK,
            message='Device token removed successfully.',
            data={'deleted': int(deleted or 0)},
        )
