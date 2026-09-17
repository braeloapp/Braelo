'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
Message model file.
---------------------------------------------------
'''

from django.utils import timezone
from mongoengine import (
    Document,
    StringField,
    ReferenceField,
    DateTimeField,
    BooleanField,
    ListField,
)

from chats.models.chat import Chat


class Message(Document):
    '''
    Message model to represent a single chat message.
    '''

    chat = ReferenceField(Chat, required=True)
    sender_id = StringField(required=True)
    content = StringField(required=False)
    read = BooleanField(default=False)
    # Legacy single URL (kept for older clients / history).
    media_url = StringField()
    # Up to 5 image URLs for album-style chat photos.
    media_urls = ListField(StringField(), default=list)
    created_at = DateTimeField()

    meta = {
        'collection': 'messages',
        'ordering': ['-created_at'],
        'indexes': [
            'chat',
            (
                'chat',
                'created_at',
            ),
        ],
    }

    def save(self, *args, **kwargs):
        self.created_at = timezone.now()
        return super(Message, self).save(*args, **kwargs)
