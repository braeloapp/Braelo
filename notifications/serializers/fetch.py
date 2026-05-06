'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
get notifications endpoints.
---------------------------------------------------
'''

from rest_framework_mongoengine import serializers
from notifications.models import Notification


class NotificationSerializer(serializers.DocumentSerializer):
    class Meta:
        model = Notification
        fields = [
            'id',
            'user_id',
            'type',
            'title',
            'body',
            'data',
            'is_read',
            'sent',
            'sent_at',
            'created_at',
        ]
        read_only_fields = ['id']
