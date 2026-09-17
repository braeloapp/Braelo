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

from rest_framework import serializers as drf_serializers
from rest_framework_mongoengine import serializers
from chats.models.message import Message


class MessageSerializer(serializers.DocumentSerializer):
    # Photo-only chat messages have no text body.
    content = drf_serializers.CharField(
        required=False, allow_blank=True, allow_null=True, default=''
    )

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
        extra_kwargs = {
            'media_url': {'required': False, 'allow_blank': True, 'allow_null': True},
            'media_urls': {'required': False},
            'read': {'required': False},
        }

    def validate(self, attrs):
        content = (attrs.get('content') or '').strip()
        media_url = attrs.get('media_url')
        media_urls = attrs.get('media_urls') or []
        has_media = bool(media_url) or bool(media_urls)
        if not content and not has_media:
            raise drf_serializers.ValidationError(
                {'content': 'Message text or photo is required.'}
            )
        attrs['content'] = content
        return attrs

    def create(self, validated_data):
        return Message.objects.create(**validated_data)
