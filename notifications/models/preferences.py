'''Per-user notification delivery preferences.'''

from django.utils import timezone
from mongoengine import BooleanField, DateTimeField, Document, IntField


class NotificationPreference(Document):
    user_id = IntField(required=True, unique=True)
    messages = BooleanField(default=True)
    listing_activity = BooleanField(default=True)
    business_activity = BooleanField(default=True)
    marketing = BooleanField(default=True)
    system_security = BooleanField(default=True)
    admin_announcements = BooleanField(default=True)
    updated_at = DateTimeField()

    meta = {
        'collection': 'notification_preferences',
        'indexes': [
            {'fields': ['user_id'], 'unique': True},
        ],
    }

    def save(self, *args, **kwargs):
        self.updated_at = timezone.now()
        return super().save(*args, **kwargs)

    @classmethod
    def for_user(cls, user_id):
        uid = int(user_id)
        existing = cls.objects(user_id=uid).first()
        if existing:
            return existing
        row = cls(user_id=uid)
        row.save()
        return row
