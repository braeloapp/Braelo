'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
message serializer file.
---------------------------------------------------
'''

from rest_framework_mongoengine import serializers
from chats.models.message import Message


class MessageSerializer(serializers.DocumentSerializer):

    class Meta:
        model = Message
        fields = [
            'id',
            'chat',
            'sender_id',
            'content',
            'media_url',
            'media_urls',
            'read',
            'created_at',
        ]
        read_only_fields = ['id', 'chatroom', 'sender', 'created_at']

    def create(self, validated_data):
        return Message.objects.create(**validated_data)
