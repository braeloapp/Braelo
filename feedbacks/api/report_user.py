from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework_mongoengine import generics
from helpers import response, handle_exceptions
from feedbacks.serializers import ReportMessageSerializer


class ReportMessage(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ReportMessageSerializer

    @handle_exceptions
    def post(self, request):
        '''
        Get method to make a report.
        :param request: request object. (dict)
        :return: report object. (dict)
        '''

        serializer = self.get_serializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return response(
            status=status.HTTP_201_CREATED,
            message="Report Submitted successfully",
            data=serializer.data,
        )
