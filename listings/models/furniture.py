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
from helpers.constants import FurnitureConstants as FC
from mongoengine.fields import (
    IntField,
    StringField,
    ListField,
    BooleanField,
    DateTimeField,
    DecimalField,
    PointField,
)


class FurnitureListing(Document):
    '''
    Furniture category listings.
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
    material_type = StringField(required=True)
    color = StringField(required=True)
    dimensions = StringField(required=True)

    condition = StringField(choices=FC.CONDITION, required=True)
    donation = StringField(choices=FC.DONATION, required=True)
    price = DecimalField(required=True)
    negotiable = StringField(choices=FC.NEGOTIABLE, required=True)

    # Couch
    seating_capacity = StringField(required=False)
    upholstery_material = StringField(required=False)

    # Tables
    table_type = StringField(required=False)
    shapes = StringField(required=False)

    # Chairs
    chair_type = StringField(required=False)
    weight_capacity = StringField(required=False)

    # Bed
    bed_size = StringField(required=False)
    mattress_included = StringField(
        choices=FC.MATTRESS_INCLUDED, required=False
    )

    # Custom furniture
    customization = StringField(required=False)
    lead_time = StringField(required=False)

    # Business Checks
    from_business = BooleanField(required=False, default=False)
    listing_clicks = IntField(default=0, required=False)

    # Timestamps
    created_at = DateTimeField()
    updated_at = DateTimeField()

    # Status
    is_active = BooleanField(required=True, default=True)

    meta = {
        'collection': 'furniture_listing',
        'ordering': ['-created_at'],
        'indexes': [
            {'fields': ['title']},
            {'fields': ['category']},
            {'fields': ['subcategory']},
        ],
    }
