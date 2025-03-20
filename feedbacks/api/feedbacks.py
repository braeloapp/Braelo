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
from rest_framework.permissions import IsAuthenticated
from helpers import handle_exceptions, response
from rest_framework.exceptions import ValidationError

from feedbacks.serializers import RequestsSerializer, FeedbacksSerializer
from feedbacks.models import Requests


class SupportRequest(generics.RetrieveUpdateDestroyAPIView):
    '''
    User requests form endpoint.
    '''

    permission_classes = [IsAuthenticated]
    serializer_class = RequestsSerializer

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
        feedback_id = request.data.get('feedback_id')
        if not feedback_id:
            raise ValidationError({'Error': 'ID is required'})
        feedback = Requests.objects.filter(
            id=feedback_id, is_active=True
        ).first()
        if not feedback:
            raise ValidationError({'Error': 'No  feedback found'})
        feedback.is_active = False
        feedback.save(update_fields=['is_active'])
        return response(
            status=status.HTTP_201_CREATED,
            message='Request Deleted Successfully',
            data={},
        )

    def put(self, request, *args, **kwargs):
        feedback_id = request.data.get('feedback_id')
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
        if not feedback_id:
            raise ValidationError({'Error': 'ID is required'})

        feedback = Requests.objects.filter(
            id=feedback_id, is_active=True
        ).first()
        if not feedback:
            raise ValidationError({'Error': 'No feedback found'})

        feedback.status = request_status
        feedback.save(update_fields=['status'])

        return response(
            status=status.HTTP_201_CREATED,
            message='Status Updated Successfully',
            data={},
        )


class Feedback(generics.CreateAPIView):
    '''
    User feedback endpoint.
    '''

    permission_classes = [IsAuthenticated]
    serializer_class = FeedbacksSerializer

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
