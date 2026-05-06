'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
ASGI config for the Braelo project.

Order is important:
    1. Set DJANGO_SETTINGS_MODULE
    2. Build the HTTP ASGI application (this triggers django.setup() and
       loads INSTALLED_APPS so MongoEngine + ORM models are importable).
    3. Only **then** import the Channels routing / consumers / our JWT
       middleware. Importing them earlier raises
       ``AppRegistryNotReady`` under Daphne / uvicorn.
---------------------------------------------------
'''

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

from chats.routing import websocket_urlpatterns  # noqa: E402
from config.middleware import JWTAuthMiddlewareStack  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": JWTAuthMiddlewareStack(
            URLRouter(websocket_urlpatterns)
        ),
    }
)
