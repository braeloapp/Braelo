'''
---------------------------------------------------
Project:        Braelo
Date:           March 20, 2025
Author:         Faizan
---------------------------------------------------

Description:
Business Banner By Admin, model mongo based.
---------------------------------------------------
'''
from django.utils import timezone

from mongoengine import Document
from mongoengine.fields import (
    IntField,
    StringField,
    ListField,
    BooleanField,
    DateTimeField,
)


class AdminBusinessBanner(Document):
    user_id = IntField(required=False)
    business_email = StringField(required=True)
    business_name = StringField(required=True)
    business_banner = ListField(required=True)
    business_category = StringField(required=True)
    business_subcategory = StringField(required=True)
    created_at = DateTimeField(default=timezone.now())
    is_active = BooleanField(default=True)

    meta = {
        'collection': 'banners_by_admin',
        'ordering': ['-created_at'],
        'indexes': [
            {'fields': ['user_id']},
            {'fields': ['business_name']},
            {'fields': ['business_category']},
            {'fields': ['business_subcategory']},
        ],
    }
