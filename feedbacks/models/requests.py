'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
User Requests model.
---------------------------------------------------
'''

from mongoengine import Document
from mongoengine.fields import (
    IntField,
    StringField,
    ListField,
    DateTimeField,
    EmailField,
    BooleanField,
)


class Requests(Document):
    user_id = IntField()
    email = EmailField(required=True)
    subject = StringField(required=True)
    status = StringField(default='Active')
    description = StringField(required=True)
    attachments = ListField(required=False, default=None)
    is_active = BooleanField(default=True)
    created_at = DateTimeField()
    updated_at = DateTimeField()
    replies = ListField(default=list)

    meta = {
        'collection': 'report_issue',
        'ordering': ['-created_at'],
        'indexes': [
            {'fields': ['user_id']},
            {'fields': ['email']},
            {'fields': ['subject']},
            {'fields': ['status']},
        ],
    }
