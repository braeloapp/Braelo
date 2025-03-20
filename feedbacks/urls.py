'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
End points registry file.
---------------------------------------------------
'''

from django.urls import path
from feedbacks.api.feedbacks import SupportRequest, Feedback
from feedbacks.api.report_user import ReportMessage

urlpatterns = [
    path('request', SupportRequest.as_view(), name='user-request'),
    path('feedback', Feedback.as_view(), name='user-feedback'),
    path('user', ReportMessage.as_view(), name='report-user'),
]
