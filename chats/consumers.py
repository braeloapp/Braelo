'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
WebSocket consumer for one-to-one and group chats.

Auth contract
-------------
``config.middleware.JWTAuthMiddleware`` runs *before* the consumer and
populates ``scope["user"]``:

* Authenticated  -> ``scope["user"]`` is a real ``users.User`` instance
* Otherwise       -> ``scope["user"]`` is ``AnonymousUser``

The handshake is **always** allowed to complete (HTTP 101). If the user
is anonymous, the consumer accepts and immediately closes with a
WebSocket close code so the client can react. Returning a raw HTTP 403
mid-handshake (the original bug on Azure) makes browsers fail without
any actionable error.

WebSocket close codes used
--------------------------
* 4401 - missing / invalid / expired token
* 4404 - chat not found
* 4400 - malformed request (no peer ``user_id``)
* 4003 - chat blocked between participants
* 5000 - infrastructure failure (Redis unavailable, etc.)
---------------------------------------------------
'''

import json
import logging

import redis.exceptions
from asgiref.sync import async_to_sync
from channels.exceptions import StopConsumer
from channels.generic.websocket import WebsocketConsumer
from channels.layers import get_channel_layer
from django.utils import timezone

from .models import Chat, Message

logger = logging.getLogger("chats.ws")


class ChatroomConsumer(WebsocketConsumer):
    '''
    WebSocket handler with Redis (channel layer) integration.
    '''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.chat_type = None
        self.chatroom = None
        self.second_user_id = None
        self.chat_id = None
        self.user_id = None

    def connect(self):
        '''
        Handle the WebSocket upgrade.

        Note we always call ``self.accept()`` *before* ``self.close()``
        on rejection. That gives the client a clean WS close frame with
        a meaningful code instead of a generic 403 from the proxy.
        '''
        user = self.scope.get("user")
        path = self.scope.get("path", "<unknown>")

        if not user or not getattr(user, "is_authenticated", False):
            logger.warning("WS reject (4401 unauthenticated) path=%s", path)
            self.accept()
            self.close(code=4401)
            return

        try:
            self.user_id = str(user.id)
            self.chat_id = self.scope["url_route"]["kwargs"]["chat_id"]

            self.channel_layer = self.channel_layer or get_channel_layer()
            if self.channel_layer is None:
                logger.error("WS reject (5000): channel layer is None")
                self.accept()
                self.close(code=5000)
                return

            params = self._parse_query_params()
            self.second_user_id = params.get("user_id")
            self.chat_type = "private"

            if not self.second_user_id:
                logger.warning(
                    "WS reject (4400) user=%s chat=%s: missing peer user_id",
                    self.user_id,
                    self.chat_id,
                )
                self.accept()
                self.close(code=4400)
                return

            try:
                self.chatroom = Chat.objects.get(
                    chat_id=self.chat_id,
                    participants__all=[self.user_id, self.second_user_id],
                    participants__size=2,
                )
            except Chat.DoesNotExist:
                logger.warning(
                    "WS reject (4404) user=%s chat=%s peer=%s: chat not found",
                    self.user_id,
                    self.chat_id,
                    self.second_user_id,
                )
                self.accept()
                self.close(code=4404)
                return

            if self.chatroom.is_blocked:
                logger.info(
                    "WS reject (4003) user=%s chat=%s: chat is blocked",
                    self.user_id,
                    self.chat_id,
                )
                self.accept()
                self.close(code=4003)
                return

            if len(self.chatroom.participants) > 2:
                self.chat_type = "group"

            async_to_sync(self.channel_layer.group_add)(
                self.chat_id, self.channel_name
            )
            self.accept()
            logger.info(
                "WS accepted user=%s chat=%s type=%s",
                self.user_id,
                self.chat_id,
                self.chat_type,
            )

        except redis.exceptions.ConnectionError:
            logger.exception("WS reject (5000): redis connection error")
            try:
                self.send(json.dumps({"error": "Can't connect to Redis"}))
            except Exception:
                pass
            raise StopConsumer()

    def receive(self, text_data):
        '''
        Persist incoming chat payloads and fan them out via Redis.
        '''
        try:
            payload = json.loads(text_data)
            message_content = payload.get("message")

            if not message_content:
                self.send(text_data=json.dumps({"error": "Empty message content."}))
                return

            message = Message(
                chat=self.chatroom,
                sender_id=self.user_id,
                content=message_content,
                read=False,
                created_at=timezone.now(),
            )
            message.save()

            message_payload = {
                "sender_id": self.user_id,
                "content": message_content,
                "created_at": message.created_at.isoformat(),
            }

            async_to_sync(self.channel_layer.group_send)(
                self.chat_id,
                {"type": "chat_message", "message": message_payload},
            )

        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("WS bad payload from user=%s: %s", self.user_id, exc)
            self.send(text_data=json.dumps({"error": str(exc)}))
        except Exception:
            logger.exception("WS unexpected error in receive (user=%s)", self.user_id)
            self.send(
                text_data=json.dumps({"error": "An unexpected error occurred."})
            )

    def chat_message(self, event):
        '''
        Channel-layer fan-out handler.
        '''
        self.send(text_data=json.dumps(event["message"]))

    def disconnect(self, close_code):
        '''
        Leave the channel-layer group on disconnect.
        '''
        try:
            if self.channel_layer and self.chat_id:
                async_to_sync(self.channel_layer.group_discard)(
                    self.chat_id, self.channel_name
                )
        except Exception:
            logger.exception(
                "WS group_discard failed (user=%s chat=%s)",
                self.user_id,
                self.chat_id,
            )
        logger.info(
            "WS disconnect user=%s chat=%s code=%s",
            self.user_id,
            self.chat_id,
            close_code,
        )
        raise StopConsumer()

    def _parse_query_params(self) -> dict:
        '''
        Safe query-string parser. The previous implementation crashed on
        bare flags such as ``?user_id`` because of ``param.split('=')``
        with no default.
        '''
        from urllib.parse import parse_qs

        raw = self.scope.get("query_string") or b""
        parsed = parse_qs(raw.decode("utf-8", errors="ignore"))
        return {k: v[0] for k, v in parsed.items() if v}
