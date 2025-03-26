'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
Serializer file for Listings based endpoints
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
)


class SavedItem(Document):
    user_id = IntField()
    listing_id = ObjectIdField(required=True)
    category = StringField(required=True)
    subcategory = StringField(required=True)
    title = StringField(required=True)
    price = DecimalField(required=True)
    location = StringField(required=True)
    pictures = ListField(required=True)
    saved_at = DateTimeField(required=False)

    # Status
    is_active = BooleanField(required=True, default=True)

    meta = {
        'collection': 'saved_listings',
        'ordering': ['-created_at'],
        'indexes': [
            {'fields': ['user_id']},
            {'fields': ['listing_id']},
            {'fields': ['category']},
            {'fields': ['title']},
            {'fields': ['user_id', 'listing_id']},
        ],
    }
