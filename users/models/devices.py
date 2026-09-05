'''User device token model.'''

from django.utils import timezone
from mongoengine import DateTimeField, Document, EmailField, IntField, StringField


class UserDeviceToken(Document):
    PLATFORM_CHOICES = (('android', 'Android'), ('ios', 'iOS'))

    user_id = IntField(required=True)
    email = EmailField()
    platform = StringField(max_length=10, choices=PLATFORM_CHOICES, required=True)
    token = StringField(max_length=4096, required=True)
    updated_at = DateTimeField()

    meta = {
        'collection': 'device_token',
        'indexes': [
            'user_id',
            'token',
        ],
    }

    def save(self, *args, **kwargs):
        self.updated_at = timezone.now()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"Token for user {self.user_id} on {self.platform}"
