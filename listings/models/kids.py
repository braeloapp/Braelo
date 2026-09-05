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
from helpers.constants import KidsConstants as KC
from mongoengine.fields import (
    IntField,
    StringField,
    ListField,
    BooleanField,
    DateTimeField,
    DecimalField,
    PointField,
)


class KidsListing(Document):
    '''
    Kids category listings.
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

    # Price-related fields
    donation = StringField(choices=KC.DONATION, required=True)
    price = DecimalField(required=True)
    negotiable = StringField(choices=KC.NEGOTIABLE, required=True)

    # Common fields for subcategories
    age_range = StringField(required=True)
    expiry_date = DateTimeField(required=False)
    duration = StringField(required=False)
    certification = StringField(choices=KC.CERTIFICATION, required=False)

    # Specific fields for subcategories
    # Health
    product_type = StringField(required=False)
    # Toys
    toy_type = StringField(required=False)
    safety_standard = StringField(required=False)

    # Transport
    vehicle_type = StringField(required=False)
    weight_capacity = StringField(required=False)

    # Accessories Type
    accessories_type = StringField(required=False)

    # Classes
    subject = StringField(required=False)
    experience_level = StringField(required=False)

    # Schools/Daycare/Babysitter
    babysitter_experience = StringField(required=False)
    grades = StringField(choices=KC.KIDS_GRADES, required=False)
    no_of_children = IntField(required=False)
    age_group = StringField(required=False)
    # After school program
    activities_offered = StringField(required=False)
    # Activities
    activity_type = StringField(required=False)
    equipment_required = StringField(required=False)

    # Business Checks
    from_business = BooleanField(required=False, default=False)
    listing_clicks = IntField(default=0, required=False)

    # Timestamps
    created_at = DateTimeField()
    updated_at = DateTimeField()

    # Status
    is_active = BooleanField(required=True, default=True)

    meta = {
        'collection': 'kids_listing',
        'ordering': ['-created_at'],
        'indexes': [
            {'fields': ['title']},
            {'fields': ['category']},
            {'fields': ['subcategory']},
        ],
    }
