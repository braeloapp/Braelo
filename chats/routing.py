'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
WebSocket URL routing.

Pattern:
    wss://<host>/chat_id/<chat_id>?token=<JWT>&user_id=<peer_id>

A ``re_path`` is used (instead of ``path``) so we explicitly accept
either ``/chat_id/<id>`` or ``/chat_id/<id>/``. Daphne is strict about
trailing slashes – matching both avoids a class of "404 / silent close"
bugs in production.
---------------------------------------------------
'''

from django.urls import re_path

from .consumers import ChatroomConsumer

websocket_urlpatterns = [
    re_path(
        r"^chat_id/(?P<chat_id>[^/]+)/?$",
        ChatroomConsumer.as_asgi(),
        name="ws-chatroom",
    ),
]
