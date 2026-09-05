'''Authenticated notification preference endpoints.'''

from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated

from helpers import handle_exceptions, response
from notifications.serializers.preferences import NotificationPreferenceSerializer
from notifications.services.preferences import preference_payload, upsert_preferences


class NotificationPreferencesAPI(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = NotificationPreferenceSerializer

    @handle_exceptions
    def get(self, request, *args, **kwargs):
        return response(
            status=status.HTTP_200_OK,
            message='Notification preferences fetched successfully.',
            data=preference_payload(request.user.id),
        )

    @handle_exceptions
    def put(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = upsert_preferences(request.user.id, serializer.validated_data)
        return response(
            status=status.HTTP_200_OK,
            message='Notification preferences updated successfully.',
            data=data,
        )

    def patch(self, request, *args, **kwargs):
        return self.put(request, *args, **kwargs)
