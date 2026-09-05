'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
Vehicle Listing model mongo based.
---------------------------------------------------
'''

from mongoengine import Document
from helpers.constants import EventConstants as EC
from mongoengine.fields import (
    IntField,
    StringField,
    ListField,
    BooleanField,
    DateTimeField,
    DecimalField,
    FloatField,
    PointField,
)


class EventsListing(Document):
    '''
    Events category listings.
    '''

    user_id = IntField()
    category = StringField(required=True)
    subcategory = StringField(required=True)
    pictures = ListField(required=True)
    title = StringField(required=True)
    description = StringField(required=True)
    keywords = ListField(StringField(required=True), required=True)
    listing_coordinates = PointField(required=True)
    location = StringField(required=False)

    # category based
    event_type = StringField(required=True)
    event_date = StringField(required=True)
    expected_audience = IntField(required=True)
    special_feature = StringField(required=True)

    ticket_price = DecimalField(required=True)
    negotiable = StringField(choices=EC.NEGOTIABLE, required=True)

    # Networking event
    industry_focus = StringField(required=False)
    speaker_list = StringField(required=False)
    # Concert
    genre = StringField(required=False)
    # festivals
    no_of_days = IntField(required=False)
    theme = StringField(required=False)
    major_attraction = StringField(required=False)

    # Business Checks
    from_business = BooleanField(required=False, default=False)
    listing_clicks = IntField(default=0, required=False)

    # Timestamps
    created_at = DateTimeField()
    updated_at = DateTimeField()

    # Status
    is_active = BooleanField(required=True, default=True)

    meta = {
        'collection': 'events_listing',
        'ordering': ['-created_at'],
        'indexes': [
            {'fields': ['title']},
            {'fields': ['category']},
            {'fields': ['subcategory']},
        ],
    }
