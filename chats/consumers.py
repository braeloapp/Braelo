'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
consumer socket file.
---------------------------------------------------
'''

import json
from asgiref.sync import async_to_sync
from channels.exceptions import DenyConnection
from channels.generic.websocket import WebsocketConsumer
from channels.exceptions import StopConsumer
from channels.layers import get_channel_layer
from django.utils import timezone
from mongoengine import DoesNotExist
import redis.exceptions
from .models import *


class ChatroomConsumer(WebsocketConsumer):
    '''
    WebSocket handler with Redis integration.
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
        WebSocket connect handler.
        '''
        try:
            if not self.scope['user'].is_authenticated:
                raise DenyConnection('Invalid or expired token.')

            self.user_id = str(self.scope['user'].id)
            self.chat_id = self.scope['url_route']['kwargs']['chat_id']
            self.channel_layer = (
                self.channel_layer or get_channel_layer()
            )  # Ensure it's not None

            if self.channel_layer is None:
                self.close()
                return  # Exit early if channel_layer is still None
            query_params = self.scope['query_string'].decode('utf-8')
            params = dict(param.split('=') for param in query_params.split('&'))
            self.second_user_id = params.get('user_id')
            self.chat_type = 'private'

            if not self.second_user_id:
                self.close()
                return

            try:
                self.chatroom = Chat.objects.get(
                    chat_id=self.chat_id,
                    participants__all=[self.user_id, self.second_user_id],
                    participants__size=2,
                )
            except Chat.DoesNotExist:
                raise DenyConnection('Chat matching query does not exist.')

            if len(self.chatroom.participants) > 2:
                self.chat_type = 'group'

            # Add user to the Redis group
            async_to_sync(self.channel_layer.group_add)(
                self.chat_id, self.channel_name
            )
            self.accept()

        except redis.exceptions.ConnectionError:
            self.send(json.dumps({"error": "Can't connect to Redis"}))
            raise StopConsumer()  # Gracefully stop without crashing

    def receive(self, text_data):
        '''
        Handles incoming WebSocket messages from the client.
        '''
        try:
            text_data_json = json.loads(text_data)
            message_content = text_data_json.get('message')

            if not message_content:
                self.send(
                    text_data=json.dumps({'error': 'Empty message content.'})
                )
                return

            # Save and broadcast the message
            message = Message(
                chat=self.chatroom,
                sender_id=self.user_id,
                content=message_content,
                read=False,
                created_at=timezone.now(),
            )
            message.save()

            message_payload = {
                'sender_id': self.user_id,
                'content': message_content,
                'created_at': message.created_at.isoformat(),
            }

            # Broadcast message using Redis
            async_to_sync(self.channel_layer.group_send)(
                self.chat_id,
                {
                    'type': 'chat_message',
                    'message': message_payload,
                },
            )

        except (json.JSONDecodeError, ValueError) as e:
            self.send(text_data=json.dumps({'error': str(e)}))
        except Exception as e:
            self.send(
                text_data=json.dumps({'error': 'An unexpected error occurred.'})
            )

    def chat_message(self, event):
        '''
        Event handler for broadcasting messages to WebSocket clients in the group.
        '''
        self.send(text_data=json.dumps(event['message']))

    def disconnect(self, close_code):
        '''
        Handles WebSocket disconnections.
        '''
        async_to_sync(self.channel_layer.group_discard)(
            self.chat_id, self.channel_name
        )
        raise StopConsumer()
