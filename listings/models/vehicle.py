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
from mongoengine.fields import (
    IntField,
    StringField,
    ListField,
    BooleanField,
    DateTimeField,
    DecimalField,
    PointField,
)
from helpers.constants import VehicleConstants as VC


class VehicleListing(Document):
    '''
    Vehicle category listings.
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

    make = StringField(required=True)
    model = StringField(required=True)
    year = IntField(required=True)
    color = StringField(required=True)
    mileage = IntField(required=False)
    fuel_type = StringField(required=False)

    transmission = StringField(choices=VC.TRANSMISSION, required=False)
    condition = StringField(choices=VC.CONDITION, required=True)
    price = DecimalField(required=True)
    negotiable = StringField(choices=VC.NEGOTIABLE, required=True)

    # Cars
    number_of_doors = StringField(choices=VC.NUMBER_OF_DOORS, required=False)
    purpose = StringField(choices=VC.PURPOSE, required=False)

    # Truck
    Load_capacity = IntField(required=False)  # issue discuss

    # Bike
    bike_type = StringField(required=False)
    # Boat
    boat_length = IntField(required=False)  # issue discuss
    # Vans
    passenger_capacity = IntField(required=False)
    # Parts and Accessories
    part_name = StringField(required=False)
    # Rentals
    for_sale = StringField(choices=VC.FOR_SALE, required=False)
    rentals = StringField(choices=VC.RENTALS, required=False)
    vehicle_type = StringField(required=False)
    rental_duration = StringField(required=False)

    # Business Checks
    from_business = BooleanField(required=False, default=False)
    listing_clicks = IntField(default=0, required=False)

    # Timestamps
    created_at = DateTimeField()
    updated_at = DateTimeField()

    # Status
    is_active = BooleanField(required=True, default=True)

    meta = {
        'collection': 'vehicle_listing',
        'ordering': ['-created_at'],
        'indexes': [
            {'fields': ['title']},
            {'fields': ['category']},
            {'fields': ['subcategory']},
        ],
    }
