'''
---------------------------------------------------
Project:        Braelo
Date:           March 20, 2025
Author:         Faizan
---------------------------------------------------

Description:
API classes for admin_panel.
---------------------------------------------------
'''

from rest_framework import generics, status
from helpers import response, handle_exceptions
from rest_framework.permissions import IsAdminUser
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination


from users.models import User
from firebase_admin import messaging
from notifications.models import Notification
from admin_panel.serializers import UserSerializer
from feedbacks.models import Requests, ReportMessage
from feedbacks.serializers import RequestsSerializer
from notifications.serializers import NotificationSerializer
from admin_panel.serializers import BusinessBannerSerializer
from feedbacks.serializers.report_user import ReportMessageSerializer


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


class PaginateReportedUsers(PageNumberPagination):
    '''
    Listing pagination configurations.
    filters data and sends name of reported and reported_by users
    '''

    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50

    def get_paginated_response(self, data):
        paginated_data = super().get_paginated_response(data).data
        paginate_results = paginated_data.get('results')

        for record in paginate_results:
            user = User.objects.filter(
                id=str(record.get('reported_to'))
            ).first()
            record['reported_to_user'] = user.name
            user = User.objects.filter(
                id=str(record.get('reported_by'))
            ).first()
            record['reported_by_user'] = user.name

        paginated_data['results'] = paginate_results

        return response(
            status=status.HTTP_200_OK,
            message='Records fetched Successfully',
            data=paginated_data,
        )


class AllUsers(generics.ListAPIView):
    '''
    View that fetches all users for admin
    '''

    permission_classes = [IsAdminUser]
    serializer_class = UserSerializer
    queryset = User.objects.all()
    pagination_class = Pagination


class AllFeedback(generics.ListAPIView):
    '''
    View that fetches user's feedbacks for admin panel
    '''

    permission_classes = [IsAdminUser]
    queryset = Requests.objects.all()
    pagination_class = Pagination
    serializer_class = RequestsSerializer

    def get_queryset(self):
        return Requests.objects.filter(is_active=True)


class AllNotifications(generics.ListAPIView):
    '''
    View that fetches all notifications for admin
    '''

    permission_classes = [IsAdminUser]
    queryset = Notification.objects.all()
    pagination_class = Pagination
    serializer_class = NotificationSerializer


class ReportedUsers(generics.ListCreateAPIView):
    '''
    View that allows admin to take certain action on reported users
    '''

    permission_classes = [IsAdminUser]
    pagination_class = PaginateReportedUsers
    serializer_class = ReportMessageSerializer
    queryset = ReportMessage.objects.all()

    def get_queryset(self):
        return ReportMessage.objects.filter(is_active=True)

    @handle_exceptions
    def post(self, request):
        '''
        POST method to take action on a reported user.
        :param request: request object. (dict)
        :return: Succesfull message. (json)
        '''
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
    '''
    Send notification to all users from admin using FCM.
    '''

    permission_classes = [IsAdminUser]

    def post(self, request):
        '''
        POST method to send notification to all users.
        :param request: request object. (dict)
        :return: Sucessfull message. (json)
        '''
        data = request.data
        user_id = request.user.id
        title = data.get('title')
        body = data.get('body')

        notification = Notification.objects.create(
            user_id=[user_id],
            title=title,
            body=body,
            type='admin',
            data={
                'message': 'this is admin',
            },
        )
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            topic='Braelo',
            data={'notification_id': str(notification.id)},
        )
        messaging.send(message)

        return response(
            status=status.HTTP_200_OK,
            message='Notification Sent To All Users',
            data={},
        )


class AdminBanner(generics.CreateAPIView):
    '''
    View that allows an admin to create a banner for a business
    '''

    permission_classes = [IsAdminUser]
    serializer_class = BusinessBannerSerializer

    def post(self, request):
        '''
        POST method to update a listing.
        :param request: request object. (dict)
        :return: Successfull message. (json)
        '''
        data = request.data
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return response(
            status=status.HTTP_201_CREATED,
            message='Banner Created Succesfully',
            data={},
        )
