from rest_framework import generics, status
from helpers import response, handle_exceptions
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAdminUser
from rest_framework.pagination import PageNumberPagination


from users.models import User
from feedbacks.models import Requests, ReportMessage
from feedbacks.serializers import RequestsSerializer
from admin_panel.serializers import UserSerializer
from notifications.models import Notification
from notifications.serializers import NotificationSerializer
from firebase_admin import messaging


class Pagination(PageNumberPagination):
    '''
    Listing pagination configurations.
    '''

    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50

    def get_paginated_response(self, data):
        paginated_data = super().get_paginated_response(data).data
        return response(
            status=status.HTTP_200_OK,
            message='Records fetched Successfully',
            data=paginated_data,
        )


class AllUsers(generics.ListAPIView):

    permission_classes = [IsAdminUser]
    serializer_class = UserSerializer
    queryset = User.objects.all()
    pagination_class = Pagination


class AllFeedback(generics.ListAPIView):

    permission_classes = [IsAdminUser]
    queryset = Requests.objects.all()
    pagination_class = Pagination
    serializer_class = RequestsSerializer

    def get_queryset(self):
        return Requests.objects.filter(is_active=True)


class AllNotifications(generics.ListAPIView):

    permission_classes = [IsAdminUser]
    queryset = Notification.objects.all()
    pagination_class = Pagination
    serializer_class = NotificationSerializer


class ReportedUsers(generics.CreateAPIView):

    permission_classes = [IsAdminUser]

    @handle_exceptions
    def post(self, request):
        report_id = request.data.get("report_id")
        user_id = request.data.get("user_id")
        action_type = request.data.get("action_type")

        # Validate required fields
        if not report_id:
            raise ValidationError({"Error": "report_id is required"})
        if not user_id:
            raise ValidationError({"Error": "user_id is required"})
        if action_type not in ("warn", "ban", "ignore"):
            raise ValidationError(
                {"Error": 'action_type must be {"warn", "ban", "ignore"}'}
            )

        # Fetch user and report
        user = User.objects.filter(id=user_id).first()
        if not user:
            raise ValidationError({"Error": "User not found"})

        report = ReportMessage.objects.filter(
            id=report_id, is_active=True
        ).first()
        if not report:
            raise ValidationError({"Error": "No Report Found"})

        if action_type == "warn":
            user.is_warned = True
            if user.is_warned:  # If already warned, ban the user
                user.is_banned = True

            user.save(
                update_fields=(
                    ["is_warned", "is_banned"]
                    if user.is_banned
                    else ["is_warned"]
                )
            )

        elif action_type == "ban":
            user.is_banned = True
            user.save(update_fields=["is_banned"])

        report.is_active = False
        report.status = "Solved"
        report.save(update_fields=["is_active", "status"])

        return response(
            status=status.HTTP_200_OK,
            message='Case Solved',
            data={},
        )


class SendAdminNotification(generics.CreateAPIView):

    permission_classes = [IsAdminUser]

    def post(self, request):

        data = request.data
        user_id = request.user.id
        title = data.get('title')
        body = data.get('body')
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            topic='Braelo',
        )
        messaging.send(message)
        Notification.objects.create(
            user_id=[user_id],
            title=title,
            body=body,
            type='admin',
            data={
                'message': 'this is admin',
            },
        )

        return response(
            status=status.HTTP_200_OK,
            message='Notification Sent To All Users',
            data={},
        )
