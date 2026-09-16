'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
Chat endpoint file.
---------------------------------------------------
'''

import json
import shortuuid
from mongoengine import Q
from django.utils import timezone
from users.models import User, Business
from rest_framework.views import APIView
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from rest_framework.exceptions import NotFound, ValidationError

from chats.models import Chat, Message
from chats.serializers.chat import ChatSerializer
from chats.services import (
    assert_not_blocked,
    assert_user_can_chat,
    block_user,
    first_media_url,
    is_participant,
    message_preview,
    peer_user_id,
    unblock_user,
    user_display_name,
)

from helpers import response, handle_exceptions
from users.services.rate_limit import enforce_rate_limit


class ChatroomPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100

    def get_paginated_response(self, data):
        user = self.request.user
        user_id = str(user.id)

        paginated_data = super().get_paginated_response(data).data
        paginate_results = paginated_data.get('results')

        for record in paginate_results:
            messages = Message.objects.filter(
                chat=record.get('id'), read=False, sender_id__ne=user_id
            )
            participants = record.get('participants')
            second_user_id = next(val for val in participants if val != user_id)
            receiver = record.get('receiver')
            receiver_id = receiver.get('user_id')
            sender = record.get('sender')
            sender_id = sender.get('user_id')

            user_type = None
            # finding out who is the online user
            # And getting the second user for searching of their records
            if str(receiver_id) == user_id:
                user_type = sender.get('user_type')
            elif str(sender_id) == user_id:
                user_type = receiver.get('user_type')

            messages_count = messages.count()
            last_message = Message.objects.filter(chat=record.get('id')).first()

            if user_type == 'user':
                second_user = User.objects.filter(id=second_user_id).first()
                record['user_picture'] = (
                    first_media_url(getattr(second_user, 'profile_picture', None))
                    if second_user
                    else None
                )
                record['user_name'] = user_display_name(second_user) or 'User'
            elif user_type == 'business':
                second_user = Business.objects.filter(
                    user_id=second_user_id
                ).first()
                record['business_picture'] = (
                    first_media_url(getattr(second_user, 'business_logo', None))
                    if second_user
                    else None
                )
                record['business_name'] = (
                    getattr(second_user, 'business_name', None) or 'Business'
                )
                if second_user is None:
                    fallback_user = User.objects.filter(id=second_user_id).first()
                    record['user_name'] = user_display_name(fallback_user) or 'User'
            else:
                fallback_user = User.objects.filter(id=second_user_id).first()
                record['user_picture'] = first_media_url(
                    getattr(fallback_user, 'profile_picture', None)
                ) if fallback_user else None
                record['user_name'] = user_display_name(fallback_user) or 'User'

            record['unread_messages'] = messages_count

            created_at = getattr(last_message, 'created_at', None)
            record['message_created_at'] = (
                created_at.isoformat() if created_at else ''
            )
            record['last_message'] = (
                message_preview(last_message) if last_message else ''
            )

        paginated_data['results'] = paginate_results

        return response(
            status=status.HTTP_200_OK,
            message='chatrooms fetched Successfully',
            data=paginated_data,
        )


class CreateChatroomApi(generics.CreateAPIView):
    '''
    API endpoint to either create a new chatroom or retrieve an existing one.
    The chatroom is identified by participants' user IDs.
    '''

    serializer_class = ChatSerializer
    permission_classes = [IsAuthenticated]

    def assign_roles(self, user_id, user_type):
        '''
        validate and storing user and second user ids
        '''
        user_type = self._normalize_role_flag(user_type)
        if user_type not in {'true', 'false'}:
            raise ValidationError(
                {
                    'error': (
                        'Unable to start chat. Invalid chat role.'
                    )
                }
            )
        if user_type == 'true':
            if not self._user_has_active_business(user_id):
                raise ValidationError(
                    {
                        'error': (
                            'Unable to start chat. This user is not '
                            'associated with a business.'
                        )
                    }
                )

        return {
            'user_id': user_id,
            'user_type': 'business' if user_type == 'true' else 'user',
        }

    @staticmethod
    def _user_has_active_business(user_id):
        '''True when an active Business doc exists for ``user_id``.'''
        try:
            from mongoengine.connection import ConnectionFailure
        except ImportError:  # pragma: no cover
            ConnectionFailure = Exception  # type: ignore[misc, assignment]

        try:
            return (
                Business.objects.filter(user_id=user_id, is_active=True).first()
                is not None
            )
        except ConnectionFailure:
            return False
        except Exception as exc:
            # CI / local without MongoEngine default connection
            message = str(exc).lower()
            if (
                'default connection' in message
                or 'not connected' in message
                or 'connectionfailure' in message
            ):
                return False
            raise


    @staticmethod
    def _normalize_role_flag(value):
        '''Accept bool / "true"|"false" / 1|0 from JSON or multipart.'''
        if isinstance(value, bool):
            return 'true' if value else 'false'
        if value is None:
            return None
        text = str(value).strip().lower()
        if text in {'true', '1', 'yes'}:
            return 'true'
        if text in {'false', '0', 'no'}:
            return 'false'
        return text

    def get_chatroom(self, user_id, second_user_id, receiver_type, sender_type):
        '''
        Check if a chatroom exists for the two participants.
        '''
        chatroom = Chat.objects.filter(
            participants__all=[user_id, second_user_id],
            receiver__user_type=receiver_type,
            sender__user_type=sender_type,
        )
        if chatroom.count() > 0:
            return chatroom.first()
        return None

    @handle_exceptions
    def post(self, request, *args, **kwargs):
        '''
        Handle the creation or retrieval of a chatroom.
        '''
        assert_user_can_chat(request.user)
        enforce_rate_limit(request, 'chat-create', extra_key=str(request.user.id))
        user_id = str(request.user.id)  # Get the current user's ID
        second_user_id = request.data.get('user_id')
        receiver_type = request.data.get('receiver')
        sender_type = request.data.get('sender')

        if not second_user_id:
            raise ValidationError(
                {'error': 'Unable to start chat. Please try again.'}
            )
        if str(second_user_id) == user_id:
            raise ValidationError(
                {'error': 'Unable to start chat with yourself.'}
            )
        assert_not_blocked(user_id, second_user_id)

        receiver = self.assign_roles(second_user_id, receiver_type)
        sender = self.assign_roles(user_id, sender_type)
        receiver_type = receiver.get('user_type')
        sender_type = sender.get('user_type')

        user_exist = User.objects.filter(id=second_user_id).exists()
        if not user_exist:
            raise ValidationError(
                {
                    'error': (
                        'Unable to start chat. This user does not exist.'
                    )
                }
            )

        chatroom = self.get_chatroom(
            user_id, second_user_id, receiver_type, sender_type
        )

        if chatroom:
            return response(
                status=status.HTTP_201_CREATED,
                message='Chat fetched successfully',
                data=ChatSerializer(chatroom).data,
            )

        # If the chatroom doesn't exist, create a new one
        new_chatroom = Chat(
            receiver=receiver,
            sender=sender,
            participants=[user_id, second_user_id],
            is_active=True,
            created_at=timezone.now(),
            updated_at=timezone.now(),
            chat_id=shortuuid.uuid(),
        )
        new_chatroom.save()
        from users.services.business_analytics import record_new_inquiry
        from users.services.business_settings import maybe_send_business_welcome

        if receiver_type == 'business':
            record_new_inquiry(second_user_id, user_id)
        if sender_type == 'business':
            record_new_inquiry(user_id, second_user_id)
        maybe_send_business_welcome(new_chatroom, user_id)
        data = ChatSerializer(new_chatroom).data
        return response(
            status=status.HTTP_201_CREATED,
            message='Chat created successfully',
            data=data,
        )


class DeleteChatroomApi(APIView):
    '''
    API to delete a chatroom and its associated messages.
    '''

    permission_classes = [IsAuthenticated]

    @handle_exceptions
    def delete(self, request, *args, **kwargs):
        chatroom_id = kwargs.get('chat_id')
        user_id = str(request.user.id)
        if not chatroom_id:
            return response(
                status=status.HTTP_400_BAD_REQUEST,
                message='Chatroom ID is required in query parameters.',
                data={},
            )
        # Fetch the chatroom
        chatroom = Chat.objects.filter(chat_id=chatroom_id).first()

        if not chatroom:
            return response(
                status=status.HTTP_404_NOT_FOUND,
                message='Chatroom not found.',
                data={},
            )

        if user_id not in chatroom.participants:
            return response(
                status=status.HTTP_403_FORBIDDEN,
                message='You are not authorized to delete this chatroom.',
                data={},
            )

        # Delete all messages in the chatroom
        Message.objects.filter(chat=chatroom).delete()

        # Delete the chatroom
        chatroom.delete()

        return response(
            status=status.HTTP_200_OK,
            message='Chatroom and its messages deleted successfully.',
            data={},
        )


class ChatroomListApi(generics.ListAPIView):

    permission_classes = [IsAuthenticated]
    serializer_class = ChatSerializer
    pagination_class = ChatroomPagination
    http_method_names = ['get', 'head', 'options']

    def get_queryset(self):
        # Filter chatroom's where the user is a participant
        user_id = str(self.request.user.id)
        user_type = self.request.GET.get('user_type')
        if user_type not in ('user', 'business'):
            raise ValidationError(
                {'user_type': 'Type must be user or business'}
            )

        query = Q(receiver__user_id=user_id, receiver__user_type=user_type) | Q(
            sender__user_id=user_id, sender__user_type=user_type
        )

        # will return chatrooms based on the user status at the time of creation
        return Chat.objects.filter(query).order_by('-updated_at')


class ChatroomDetailApi(generics.ListAPIView):

    permission_classes = [IsAuthenticated]
    serializer_class = ChatSerializer

    def get_queryset(self):
        return Chat.objects.all()

    def get(self, request, **kwargs):
        chat_id = self.kwargs['chat_id']
        user_id = str(self.request.user.id)
        chat = Chat.objects.filter(chat_id=chat_id).first()
        if not chat or not is_participant(chat, user_id):
            return response(
                status=status.HTTP_403_FORBIDDEN,
                message='You are not authorized to view this chatroom.',
                data={},
            )
        chat_data = self.get_serializer(chat)

        return response(
            status=status.HTTP_200_OK,
            message='Chatroom Fetched Successfully',
            data=chat_data.data,
        )


class BlockChatRoom(generics.CreateAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user_id = str(request.user.id)
        room_id = request.data.get('room_id')
        is_block = request.data.get('block')

        if is_block is None:
            raise ValidationError({'error': 'Must provide block status.'})
        if room_id is None:
            raise ValidationError({'error': 'Must provide _id of chatroom.'})

        room = Chat.objects.filter(id=room_id).first()
        if not room:
            raise ValidationError({'error': 'Chatroom not found.'})

        if user_id not in room.participants:
            raise ValidationError(
                {'error': 'You are not a participant of this chat.'}
            )

        peer = peer_user_id(room, user_id)
        if is_block.lower() == 'true':
            if peer:
                block_user(user_id, peer)
            else:
                room.update(set__is_blocked=True)
            return response(
                status=status.HTTP_200_OK, message='Room Blocked', data={}
            )
        elif is_block.lower() == 'false':
            if peer:
                try:
                    unblock_user(user_id, peer)
                except ValidationError:
                    room.update(set__is_blocked=False)
            else:
                room.update(set__is_blocked=False)
            return response(
                status=status.HTTP_200_OK, message='Room Unblocked', data={}
            )
        else:
            raise ValidationError(
                {'error': 'Invalid block status, must be "true" or "false".'}
            )
