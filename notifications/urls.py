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
from notifications.api.events import EventNotificationAPI
from notifications.api.fetch import FetchNotificationsAPI
from notifications.api.operations import (
    MarkNotificationsAsReadAPI,
    DeleteNotificationsAPI,
)
from notifications.api.preferences import NotificationPreferencesAPI

urlpatterns = [
    path('paginate', FetchNotificationsAPI.as_view()),
    path('send', EventNotificationAPI.as_view()),
    path('read', MarkNotificationsAsReadAPI.as_view()),
    path('delete', DeleteNotificationsAPI.as_view()),
    path('preferences', NotificationPreferencesAPI.as_view()),
]
