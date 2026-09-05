'''
Business messaging settings: welcome message and saved replies.
'''

import uuid

from django.utils import timezone
from mongoengine import Document, EmbeddedDocument
from mongoengine.fields import (
    BooleanField,
    DateTimeField,
    EmbeddedDocumentListField,
    IntField,
    StringField,
)


class SavedReply(EmbeddedDocument):
    reply_id = StringField(required=True)
    shortcut = StringField(required=True, max_length=80)
    body = StringField(required=True, max_length=2000)
    created_at = DateTimeField()
    updated_at = DateTimeField()

    def to_public_dict(self):
        return {
            'reply_id': self.reply_id,
            'shortcut': self.shortcut,
            'body': self.body,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class BusinessSettings(Document):
    user_id = IntField(required=True, unique=True)
    welcome_message = StringField(default='', max_length=2000)
    welcome_enabled = BooleanField(default=False)
    response_suggestions_enabled = BooleanField(default=False)
    saved_replies = EmbeddedDocumentListField(SavedReply)
    created_at = DateTimeField()
    updated_at = DateTimeField()

    meta = {
        'collection': 'business_settings',
        'indexes': [
            {'fields': ['user_id'], 'unique': True},
        ],
    }

    def to_public_dict(self):
        return {
            'user_id': self.user_id,
            'welcome_message': self.welcome_message or '',
            'welcome_enabled': bool(self.welcome_enabled),
            'response_suggestions_enabled': bool(
                self.response_suggestions_enabled
            ),
            'saved_replies': [reply.to_public_dict() for reply in self.saved_replies],
        }


def new_reply_id():
    return uuid.uuid4().hex


def stamp_now():
    return timezone.now()
