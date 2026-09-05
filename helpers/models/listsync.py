'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
Listings synchronization based endpoints.
---------------------------------------------------
'''

from mongoengine import Document
from mongoengine.fields import (
    IntField,
    StringField,
    ListField,
    BooleanField,
    DateTimeField,
    DecimalField,
    ObjectIdField,
    PointField,
)


class ListSync(Document):
    user_id = IntField(required=True)
    listing_id = ObjectIdField(required=True)
    category = StringField(required=True)
    subcategory = StringField(required=True)
    title = StringField(required=True)
    keywords = ListField(StringField(required=True), required=True)
    listing_coordinates = PointField(required=True)
    location = StringField(required=False)
    price = DecimalField(required=False)
    salary_range = StringField(required=False)
    pictures = ListField(required=True)
    # Business Checks
    from_business = BooleanField(required=True)
    listing_clicks = IntField(default=0, required=False)
    created_at = DateTimeField()

    # Status
    is_active = BooleanField(required=True, default=True)

    meta = {
        'collection': 'listsync',
        'ordering': ['-created_at'],
        'indexes': [
            {'fields': ['user_id']},
            {'fields': ['listing_id']},
            {'fields': ['category']},
            {'fields': ['title']},
            # {'fields': ['user_id', 'listing_id']},
        ],
    }
