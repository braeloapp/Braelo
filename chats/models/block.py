'''
User-level block relationship.

A block is directional: ``blocker_id`` hid ``blocked_id``.
Messaging is blocked in both directions while the row exists.
Only the blocker can reverse it.
'''

from django.utils import timezone
from mongoengine import Document
from mongoengine.fields import DateTimeField, StringField


class BlockedUser(Document):
    blocker_id = StringField(required=True)
    blocked_id = StringField(required=True)
    created_at = DateTimeField()

    meta = {
        'collection': 'blocked_users',
        'indexes': [
            {
                'fields': ['blocker_id', 'blocked_id'],
                'unique': True,
            },
            {'fields': ['blocker_id']},
            {'fields': ['blocked_id']},
        ],
    }

    def save(self, *args, **kwargs):
        if not self.created_at:
            self.created_at = timezone.now()
        return super().save(*args, **kwargs)
