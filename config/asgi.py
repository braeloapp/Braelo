'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
ASGI config for Braelo project.
It exposes an ASGI callable named ``application``.

Import order matters: call get_asgi_application() before importing routing/consumers,
or Django/MongoEngine load before setup and Daphne crashes on import.
---------------------------------------------------
'''

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

django_asgi_app = get_asgi_application()

# After setup: consumers and mongoengine models are safe to import.
from channels.routing import ProtocolTypeRouter, URLRouter
from django_channels_jwt_auth_middleware.auth import JWTAuthMiddlewareStack

from chats import routing

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": JWTAuthMiddlewareStack(
            URLRouter(
                routing.websocket_urlpatterns,
            )
        ),
    }
)
