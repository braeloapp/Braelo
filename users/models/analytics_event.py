'''
Append-only business analytics events for time-series dashboards.
'''

from mongoengine import Document
from mongoengine.fields import DateTimeField, IntField, StringField


class BusinessAnalyticsEvent(Document):
    user_id = IntField(required=True)
    event_type = StringField(required=True)
    listing_id = StringField(required=False)
    actor_id = IntField(required=False)
    created_at = DateTimeField()

    meta = {
        'collection': 'business_analytics_events',
        'ordering': ['-created_at'],
        'indexes': [
            {'fields': ['user_id', '-created_at']},
            {'fields': ['user_id', 'event_type', '-created_at']},
        ],
    }
