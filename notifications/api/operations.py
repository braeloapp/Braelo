'''
Notification read/delete endpoints.
'''

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework import generics
from rest_framework.exceptions import ValidationError

from helpers import handle_exceptions, response
from notifications.models import Notification


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _user_can_access(notification, user) -> bool:
    if notification is None or user is None:
        return False
    if notification.type == 'admin':
        return True
    uid = _as_int(getattr(user, 'id', None))
    return uid is not None and uid in list(notification.user_id or [])


class MarkNotificationsAsReadAPI(generics.UpdateAPIView):
    permission_classes = [IsAuthenticated]

    @handle_exceptions
    def post(self, request, **kwargs):
        notification_id = request.data.get('notification_id')
        if not notification_id:
            raise ValidationError({'notification_id': 'notification_id is required'})
        notification = Notification.objects(id=notification_id).first()
        if not notification or not _user_can_access(notification, request.user):
            return response(
                status=status.HTTP_404_NOT_FOUND,
                message='Notification not found',
                data={},
            )
        if not notification.is_read:
            notification.is_read = True
            notification.sent = True
            notification.save()
        return response(
            status=status.HTTP_200_OK,
            message='Notification read successfully',
            data={},
        )


class DeleteNotificationsAPI(generics.DestroyAPIView):
    permission_classes = [IsAuthenticated]

    @handle_exceptions
    def post(self, request, **kwargs):
        notification_id = request.data.get('notification_id')
        if not notification_id:
            raise ValidationError({'notification_id': 'notification id required'})
        notification = Notification.objects(id=notification_id).first()
        if not notification or not _user_can_access(notification, request.user):
            return response(
                status=status.HTTP_404_NOT_FOUND,
                message='No notification found',
                data={},
            )
        notification.delete()
        return response(
            status=status.HTTP_200_OK,
            message='notification deleted successfully',
            data={},
        )
