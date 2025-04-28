'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
Chat model file.
---------------------------------------------------
'''

import shortuuid
from mongoengine import (
    Document,
    StringField,
    ListField,
    DateTimeField,
    ReferenceField,
    BooleanField,
    DictField,
    IntField,
)
from django.utils import timezone


class Chat(Document):
    '''
    Chat model to represent a conversation between two users.
    '''

    chat_id = StringField(unique=True)
    participants = ListField(StringField(), required=True)
    receiver = DictField(required=True)
    sender = DictField(required=True)
    pair_key = StringField(required=True)
    is_active = BooleanField(default=True)
    is_blocked = BooleanField(default=False)
    created_at = DateTimeField()
    updated_at = DateTimeField()

    meta = {
        'collection': 'chats',
        'indexes': [
            {
                'fields': ['chat_id'],
                'unique': True,
            },
            # {
            #     'fields': ['pair_key'],
            #     'unique': False,
            # },
        ],
    }

    def save(self, *args, **kwargs):

        self.participants = sorted(self.participants)
        # Step 2: Generate pair_key by joining participants with '_'
        self.pair_key = "_".join(self.participants)
        if not self.chat_id:
            self.chat_id = shortuuid.uuid()
        if not self.created_at:
            self.created_at = timezone.now()
        self.updated_at = timezone.now()
        return super().save(*args, **kwargs)
