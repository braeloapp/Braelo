from mongoengine import fields, Document
from mongoengine.fields import (
    IntField,
    StringField,
    DateTimeField,
    BooleanField,
)


class ReportMessage(Document):
    '''
    report message model
    '''

    # reported to / reported by
    reported_by = IntField()
    reported_to = IntField(required=True)
    report_checkbox = StringField(required=True)
    issue_description = StringField(max_length=1000)
    status = StringField(default='Pending')
    created_at = DateTimeField()
    is_active = BooleanField(default=True)

    meta = {
        'collection': 'reported_users',
        'ordering': ['-created_at'],
        'indexes': [
            {'fields': ['reported_by']},
            {'fields': ['reported_to']},
            {'fields': ['is_active']},
        ],
    }
