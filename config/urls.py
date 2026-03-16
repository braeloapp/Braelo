'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
URL configuration for Braelo project.
https://docs.djangoproject.com/en/4.2/topics/http/urls/
---------------------------------------------------
'''

from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('auth/', include('users.urls')),
    path('chats/', include('chats.urls')),
    path('listing/', include('listings.urls')),
    path('report/', include('feedbacks.urls')),
    path('admin-panel/', include('admin_panel.urls')),
    path('notifications/', include('notifications.urls')),
    path('chatbot/', include('chatbot.urls')),
]
