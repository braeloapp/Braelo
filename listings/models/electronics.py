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
from helpers.constants import ElectronicsConstants as EC
from mongoengine.fields import (
    IntField,
    StringField,
    ListField,
    BooleanField,
    DateTimeField,
    DecimalField,
    PointField,
)


class ElectronicsListing(Document):
    '''
    Electronics category listings.
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
    brand = StringField(required=True)
    model = StringField(required=True)
    warranty = StringField(required=True)

    condition = StringField(choices=EC.CONDITION, required=True)
    price = DecimalField(required=True)
    negotiable = StringField(choices=EC.NEGOTIABLE, required=True)

    # Smartphone
    operating_system = StringField(required=False)
    carrier_lock = StringField(required=False)

    # Computer
    processor = StringField(required=False)
    ram = StringField(required=False)
    storage_type = StringField(required=False)

    # Appliances
    energy_rating = StringField(required=False)
    dimension = StringField(required=False)

    # Games
    platforms = StringField(required=False)
    jenry = StringField(required=False)

    # Services and parts
    part_type = StringField(required=False)
    compatible_model = StringField(required=False)

    # Business Checks
    from_business = BooleanField(required=False, default=False)
    listing_clicks = IntField(default=0, required=False)

    # Timestamps
    created_at = DateTimeField()
    updated_at = DateTimeField()

    # Status
    is_active = BooleanField(required=True, default=True)

    meta = {
        'collection': 'electronics_listing',
        'ordering': ['-created_at'],
        'indexes': [
            {'fields': ['title']},
            {'fields': ['category']},
            {'fields': ['subcategory']},
        ],
    }
