'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
User Feedbacks/review Endpoints.
---------------------------------------------------
'''

from rest_framework import generics, status
from helpers import handle_exceptions, response
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination

from feedbacks.models import Requests, Feedbacks
from feedbacks.serializers import RequestsSerializer, FeedbacksSerializer
from users.permissions import is_staff_user


class Pagination(PageNumberPagination):
    '''
    Pagination to show feedback for admin_panel.
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


class SupportRequest(generics.RetrieveUpdateDestroyAPIView):
    '''
    User requests form endpoint.
    '''

    permission_classes = [IsAuthenticated]
    serializer_class = RequestsSerializer
    pagination_class = Pagination

    def _owned_ticket(self, request, ticket_id):
        if not ticket_id:
            raise ValidationError({'Error': 'ID is required'})
        ticket = Requests.objects.filter(id=ticket_id, is_active=True).first()
        if not ticket:
            raise ValidationError({'Error': 'No feedback found'})
        if not is_staff_user(request.user) and ticket.user_id != request.user.id:
            raise ValidationError({'Error': 'You cannot access this ticket'})
        return ticket

    @handle_exceptions
    def get(self, request, *args, **kwargs):
        queryset = Requests.objects.filter(
            user_id=request.user.id, is_active=True
        ).order_by('-created_at')
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return response(
            status=status.HTTP_200_OK,
            message='Records fetched Successfully',
            data=serializer.data,
        )

    @handle_exceptions
    def post(self, request, **kwargs):
        serializer = self.get_serializer(
            data=request.data, context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return response(
            status=status.HTTP_201_CREATED,
            message='Request Submitted Successfully',
            data=serializer.data,
        )

    @handle_exceptions
    def delete(self, request):
        feedback = self._owned_ticket(request, request.data.get('feedback_id'))
        feedback.is_active = False
        feedback.save()
        return response(
            status=status.HTTP_200_OK,
            message='Request Deleted Successfully',
            data={},
        )

    def put(self, request, *args, **kwargs):
        if not is_staff_user(request.user):
            raise ValidationError(
                {'Error': 'Only support staff can change ticket status'}
            )
        request_status = request.data.get('status')

        if request_status not in (
            'Active',
            'On Hold',
            'In Progress',
            'Resolved',
            'Closed',
        ):
            raise ValidationError(
                {
                    'Status': 'Must be either {"Active","On Hold","In Progress","Resolved","Closed"}'
                }
            )
        feedback = self._owned_ticket(request, request.data.get('feedback_id'))
        feedback.status = request_status
        feedback.save()

        return response(
            status=status.HTTP_200_OK,
            message='Status Updated Successfully',
            data={},
        )


class Feedback(generics.ListCreateAPIView):
    '''
    User feedback endpoint.
    '''

    permission_classes = [IsAuthenticated]
    serializer_class = FeedbacksSerializer
    pagination_class = Pagination

    @handle_exceptions
    def post(self, request, **kwargs):
        serializer = self.get_serializer(
            data=request.data, context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return response(
            status=status.HTTP_201_CREATED,
            message='Feedback submitted successfully',
            data=serializer.data,
        )

    def get_queryset(self):
        user_id = self.request.user.id
        queryset = Feedbacks.objects.filter(user_id=user_id)
        if self.request.GET.get('feedback') is not None:
            feedback = self.request.GET.get('feedback')
            required_fields = ['Hate', 'Dislike', 'Neutral', 'Like', 'Love']
            if feedback not in required_fields:
                raise ValidationError(
                    {'review': f'feedback must be {required_fields}'}
                )
            return queryset.filter(feedback=feedback)
        return queryset
