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

import uuid

from django.utils import timezone
from rest_framework import generics, status
from rest_framework.views import APIView
from helpers import response, handle_exceptions
from rest_framework.permissions import IsAdminUser
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination


from users.models import User
from users.models.business import Business
from firebase_admin import messaging
from notifications.models import Notification
from admin_panel.serializers import UserSerializer
from admin_panel.services.moderation import apply_user_moderation
from admin_panel.services.support import apply_support_filters
from feedbacks.models import Requests, ReportMessage, Feedbacks
from feedbacks.serializers import RequestsSerializer, FeedbacksSerializer
from users.permissions import admin_role
from users.serializers.business import BusinessSerailizer
from notifications.serializers import NotificationSerializer
from notifications.services.delivery import deliver_event_notification
from notifications.services.email import email_service
from helpers.notifications import support_reply_event
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
            reported_to = User.objects.filter(
                id=record.get('reported_to')
            ).first()
            record['reported_to_user'] = (
                reported_to.name if reported_to else None
            )
            record['reported_to_id'] = (
                reported_to.id if reported_to else record.get('reported_to')
            )
            reported_by = User.objects.filter(
                id=record.get('reported_by')
            ).first()
            record['reported_by_user'] = (
                reported_by.name if reported_by else None
            )
            record['reported_by_id'] = (
                reported_by.id if reported_by else record.get('reported_by')
            )
            record['reason'] = record.get('report_checkbox')
            record['description'] = record.get('issue_description')
            record['user_id'] = record.get('reported_to')
            record['report_id'] = record.get('id')

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


class AdminUserDetail(APIView):
    '''GET /admin-panel/users/<id> — load a user without sessionStorage.'''

    permission_classes = [IsAdminUser]

    def get(self, request, pk):
        user = User.objects.filter(id=pk).first()
        if not user:
            return response(
                status=status.HTTP_404_NOT_FOUND,
                message='User not found',
                data={},
            )
        return response(
            status=status.HTTP_200_OK,
            message='User fetched successfully',
            data=UserSerializer(user).data,
        )


class AdminBusinessDetail(APIView):
    '''GET /admin-panel/business/<id> — load a business without sessionStorage.'''

    permission_classes = [IsAdminUser]

    def get(self, request, pk):
        business = Business.objects(id=pk).first()
        if not business:
            return response(
                status=status.HTTP_404_NOT_FOUND,
                message='Business not found',
                data={},
            )
        return response(
            status=status.HTTP_200_OK,
            message='Business fetched successfully',
            data=BusinessSerailizer(business).data,
        )


class ActiveUsers(generics.ListAPIView):
    '''
    GET /admin-panel/users/active — active users only (is_active=True).
    '''

    permission_classes = [IsAdminUser]
    serializer_class = UserSerializer
    queryset = User.objects.filter(is_active=True)
    pagination_class = Pagination


class AdminMe(APIView):
    '''
    Current admin identity and role for route guards.
    '''

    permission_classes = [IsAdminUser]

    def get(self, request):
        user = request.user
        return response(
            status=status.HTTP_200_OK,
            message='OK',
            data={
                'id': user.id,
                'email': user.email,
                'name': user.name,
                'is_staff': user.is_staff,
                'is_superuser': user.is_superuser,
                'role': admin_role(user),
            },
        )


class AllAppFeedback(generics.ListAPIView):
    '''
    App reaction feedback for admin. Consumer GET is scoped to the caller.
    '''

    permission_classes = [IsAdminUser]
    pagination_class = Pagination
    serializer_class = FeedbacksSerializer

    def get_queryset(self):
        queryset = Feedbacks.objects.all()
        feedback = self.request.GET.get('feedback')
        if feedback:
            required_fields = ['Hate', 'Dislike', 'Neutral', 'Like', 'Love']
            if feedback not in required_fields:
                raise ValidationError(
                    {'review': f'feedback must be {required_fields}'}
                )
            queryset = queryset.filter(feedback=feedback)
        return queryset


class AllFeedback(generics.ListAPIView):
    '''
    View that fetches user's feedbacks for admin panel
    '''

    permission_classes = [IsAdminUser]
    pagination_class = Pagination
    serializer_class = RequestsSerializer

    def get_queryset(self):
        return apply_support_filters(
            Requests.objects.filter(is_active=True),
            self.request.GET,
        )


class SupportReply(APIView):
    '''Staff reply stored on the ticket and delivered in-app + email.'''

    permission_classes = [IsAdminUser]

    @handle_exceptions
    def post(self, request):
        ticket_id = request.data.get('ticket_id') or request.data.get(
            'feedback_id'
        )
        message = (request.data.get('message') or '').strip()
        if not ticket_id:
            raise ValidationError({'ticket_id': 'ticket_id is required'})
        if not message:
            raise ValidationError({'message': 'Reply message is required'})
        if len(message) > 4000:
            raise ValidationError({'message': 'Reply is too long'})

        ticket = Requests.objects.filter(id=ticket_id, is_active=True).first()
        if not ticket:
            raise ValidationError({'ticket_id': 'Support ticket not found'})

        now = timezone.now()
        reply = {
            'id': str(uuid.uuid4()),
            'author_type': 'admin',
            'author_id': request.user.id,
            'author_name': request.user.name or request.user.email,
            'message': message,
            'created_at': now.isoformat(),
        }
        replies = list(ticket.replies or [])
        replies.append(reply)
        ticket.replies = replies
        ticket.updated_at = now
        if ticket.status in (None, '', 'Active'):
            ticket.status = 'In Progress'
        ticket.save()

        if ticket.user_id:
            deliver_event_notification(
                support_reply_event(ticket.user_id, str(ticket.id))
            )
        email_service.send_best_effort(
            to=ticket.email,
            template_key='support_reply',
            context={
                'name': ticket.email,
                'subject': ticket.subject,
                'reply': message,
            },
        )
        return response(
            status=status.HTTP_201_CREATED,
            message='Reply sent',
            data=RequestsSerializer(ticket).data,
        )


class AllNotifications(generics.ListAPIView):
    '''
    View that fetches all notifications for admin
    '''

    permission_classes = [IsAdminUser]
    pagination_class = Pagination
    serializer_class = NotificationSerializer

    def get_queryset(self):
        # Order newest-first. `-id` is a tiebreaker for legacy records that
        # were created without a `created_at` value (Mongo ObjectId is
        # monotonic by insertion time).
        return Notification.objects.all().order_by('-created_at', '-id')


class ReportedUsers(generics.ListCreateAPIView):
    '''
    View that allows admin to take certain action on reported users
    '''

    permission_classes = [IsAdminUser]
    pagination_class = PaginateReportedUsers
    serializer_class = ReportMessageSerializer

    def get_queryset(self):
        queryset = ReportMessage.objects.all()
        params = self.request.GET
        report_status = (params.get('report_status') or '').strip()
        search_query = (params.get('search_query') or '').strip()
        creation_date = (params.get('creation_date') or '').strip()

        if report_status and report_status.lower() not in ('all', '*'):
            if report_status.lower() in ('resolved', 'solved'):
                queryset = queryset.filter(status__in=['Solved', 'Resolved'])
            elif report_status.lower() == 'ignored':
                queryset = queryset.filter(status='Ignored')
            else:
                queryset = queryset.filter(status=report_status)
        if creation_date:
            from admin_panel.services.support import day_bounds

            start, end = day_bounds(creation_date)
            if start is not None:
                queryset = queryset.filter(
                    created_at__gte=start, created_at__lt=end
                )
        if search_query:
            matching_ids = list(
                User.objects.filter(name__icontains=search_query).values_list(
                    'id', flat=True
                )
            )
            queryset = queryset.filter(
                __raw__={
                    '$or': [
                        {'reported_to': {'$in': matching_ids}},
                        {'reported_by': {'$in': matching_ids}},
                        {
                            'report_checkbox': {
                                '$regex': search_query,
                                '$options': 'i',
                            }
                        },
                        {
                            'issue_description': {
                                '$regex': search_query,
                                '$options': 'i',
                            }
                        },
                    ]
                }
            )
        return queryset

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
        notes = (request.data.get("notes") or request.data.get("resolution_notes") or "").strip()

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

        report = ReportMessage.objects.filter(id=report_id).first()
        if not report:
            raise ValidationError({"Error": "No Report Found"})
        if report.reported_to and int(report.reported_to) != int(user_id):
            raise ValidationError(
                {"Error": "user_id does not match this report"}
            )

        result = apply_user_moderation(user, action_type)
        if result['update_fields']:
            user.save(update_fields=result['update_fields'])

        now = timezone.now()
        report.is_active = False
        report.status = 'Ignored' if action_type == 'ignore' else 'Resolved'
        report.action_taken = action_type
        report.resolution_notes = notes
        report.resolved_by = request.user.id
        report.resolved_at = now
        report.save()

        return response(
            status=status.HTTP_200_OK,
            message='Case Solved',
            data={
                'action_type': action_type,
                'banned': result['banned'],
                'already_warned': result['already_warned'],
            },
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
                'type': 'admin_announcement',
                'entity_type': 'admin',
                'entity_id': '',
                'action': 'open',
            },
        )
        notification.data['entity_id'] = str(notification.id)
        notification.data['notification_id'] = str(notification.id)
        notification.save()
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            topic='Braelo',
            data={
                key: str(value) for key, value in notification.data.items()
            },
        )
        messaging.send(message)

        return response(
            status=status.HTTP_200_OK,
            message='Notification Sent To All Users',
            data={},
        )


class DeleteAdminNotification(APIView):
    '''
    Delete a notification by id (MongoDB document id).
    '''

    permission_classes = [IsAdminUser]

    @handle_exceptions
    def post(self, request, **kwargs):
        '''
        POST body: { "notification_id": "<mongo object id string>" }
        '''
        notification_id = request.data.get('notification_id')
        if not notification_id:
            raise ValidationError(
                {'notification_id': 'notification id is required'}
            )
        notification = Notification.objects(id=notification_id).first()
        if not notification:
            return response(
                status=status.HTTP_404_NOT_FOUND,
                message='Notification not found',
                data={},
            )
        notification.delete()
        return response(
            status=status.HTTP_200_OK,
            message='Notification deleted successfully',
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
