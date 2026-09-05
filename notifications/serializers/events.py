'''Event-triggered notification serializer.'''

from rest_framework_mongoengine import serializers
from rest_framework.exceptions import ValidationError

from notifications.models import Notification
from notifications.services.delivery import deliver_event_notification


class EventNotificationSerializer(serializers.DocumentSerializer):
    class Meta:
        model = Notification
        fields = ['type', 'title', 'body', 'user_id', 'data']

    def validate(self, data):
        notify_type = data.get('type')
        title = data.get('title')
        body = data.get('body')
        user_id = data.get('user_id')

        if not notify_type:
            raise ValidationError({'type': 'Valid type is required.'})
        if not title:
            raise ValidationError({'title': 'Title is required.'})
        if not body:
            raise ValidationError({'body': 'Body is required.'})
        if not user_id:
            raise ValidationError({'user_id': 'Recipient user_id is required.'})
        return data

    def create(self, validated_data):
        return deliver_event_notification(validated_data)
