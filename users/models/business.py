'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
Business Listing model mongo based.
---------------------------------------------------
'''

from mongoengine import Document
from mongoengine.fields import (
    IntField,
    StringField,
    ListField,
    BooleanField,
    DateTimeField,
    EmailField,
    PointField,
)
from rest_framework.exceptions import ValidationError


class Business(Document):
    '''
    business listings model
    '''

    user_id = IntField(required=False)
    business_name = StringField(required=True)
    business_logo = ListField(required=True)
    business_banner = ListField(required=True)
    business_address = StringField(required=True)
    business_coordinates = PointField(required=True)
    business_website = StringField(required=False)
    business_number = StringField(required=True)
    business_email = EmailField(required=True)
    business_category = StringField(required=True)
    business_subcategory = StringField(required=True)
    business_images = ListField(required=True)
    business_goals = StringField(required=False)
    business_qr = ListField(required=False)
    business_url = StringField(required=False)
    is_active = BooleanField(required=True, default=True)
    created_at = DateTimeField()
    updated_at = DateTimeField()

    meta = {
        'collection': 'business_listings',
        'ordering': ['-created_at'],
        'indexes': [
            {'fields': ['business_name']},
            {'fields': ['business_category']},
            {'fields': ['business_subcategory']},
            {'fields': ['is_active', 'business_category']},
            {'fields': [('business_coordinates', '2dsphere')]},
        ],
    }
