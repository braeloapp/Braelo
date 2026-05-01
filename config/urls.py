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
from django.http import HttpResponse
from django.urls import path, include
import os

def home(request):
    return HttpResponse("Braelo is running.")


def azure_load_probe(request):
    """Azure may request this path during instance health checks."""
    return HttpResponse("", content_type="text/plain")


def test_env(request):
    return HttpResponse({
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
        "USE_MONGO": os.getenv("USE_MONGO"),
        "BRAELO_MONGO_DB_URI": os.getenv("BRAELO_MONGO_DB_URI")
    })

urlpatterns = [
    path("", home),
    path("home/", home),
    path("robots933456.txt", azure_load_probe),
    path("test-env/", test_env),
    path('admin/', admin.site.urls),
    path('auth/', include('users.urls')),
    path('chats/', include('chats.urls')),
    path('listing/', include('listings.urls')),
    path('report/', include('feedbacks.urls')),
    path('admin-panel/', include('admin_panel.urls')),
    path('notifications/', include('notifications.urls')),
    path('chatbot/', include('chatbot.urls')),
]
