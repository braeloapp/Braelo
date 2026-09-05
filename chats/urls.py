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

from chats.api.block import BlockUserApi
from chats.api.chat import (
    BlockChatRoom,
    ChatroomListApi,
    ChatroomDetailApi,
    CreateChatroomApi,
    DeleteChatroomApi,
)
from chats.api.message import (
    MessageListCreateApi,
    MarkMessagesReadApi,
    DeleteMessageApi,
    SendChatNotification,
)

Base_url = 'chats/'

urlpatterns = [
    # Creates a new chatroom or retrieves the existing
    path('create', CreateChatroomApi.as_view()),
    # Lists all chatrooms for the authenticated user
    path('paginate', ChatroomListApi.as_view()),
    # Block a user (platform-level). Room-level flag remains at block/user.
    path('block', BlockUserApi.as_view()),
    # Block user chatroom
    path('block/user', BlockChatRoom.as_view()),
    # Delete chat
    path('delete/<str:chat_id>', DeleteChatroomApi.as_view()),
    # Get details of a specific chatroom
    path('detail/<str:chat_id>', ChatroomDetailApi.as_view()),
    # Message Management APIs
    # List or send messages in a chatroom
    # Uploads an attachment or media file to the chatroom.
    path('<str:chat_id>/messages', MessageListCreateApi.as_view()),
    # Mark the message as read
    path('<str:chat_id>/messages/read', MarkMessagesReadApi.as_view()),
    # Deletes a message from a chatroom.
    path('delete/<str:chat_id>/<str:message_id>', DeleteMessageApi.as_view()),
    # notify user for new chat
    path(
        'notification/<str:chat_id>/<str:message_id>',
        SendChatNotification.as_view(),
    ),
]

# 3. Search Messages
# Endpoint: GET /api/chatrooms/<chat_id>/messages/search/
# Query Params: ?q=<keyword>
# Response:
# [
#   {
#     "message_id": "5678",
#     "content": "Search result!"
#   }
# ]
# Description: Searches for messages in a chatroom based on a keyword.


# User-Specific APIs
# ==================

# 2. Fetch Notifications
# Endpoint: GET /api/notifications/
# Response:
# [
#   { "notification_id": "123", "content": "New message", "read": false }
# ]
# Description: Retrieves notifications for the authenticated user.
