'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
Real Estate Listing model mongo-based.
---------------------------------------------------
'''

from mongoengine import fields, Document
from mongoengine.fields import (
    IntField,
    StringField,
    ListField,
    BooleanField,
    FloatField,
    PointField,
)
from helpers.constants import RealEstateConstants as REC


class RealEstateListing(Document):
    '''
    Real Estate category listings.
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

    # Common Start fields
    property_type = StringField(required=True)
    bedrooms = IntField(min_value=0, required=True)
    bathrooms = IntField(min_value=0, required=True)
    size = FloatField(required=True)
    condition = StringField(choices=REC.CONDITION, required=True)
    furnished = StringField(choices=REC.FURNISHED, default='UNFURNISHED')

    # Last
    other = StringField(required=False)
    lease_managed_by = StringField(choices=REC.LEASE_MANAGED_BY, required=False)
    price = FloatField(required=True)
    negotiable = StringField(choices=REC.NEGOTIABLE, required=True)

    # Category Based
    # Apartment & House & Mobile Home
    basement = StringField(choices=REC.BASEMENT, required=False)
    # Common in commercial
    parking_and_cost = StringField(required=False)
    lease_terms = StringField(choices=REC.LEASE_TERMS, required=False)
    maintenance_policy = StringField(required=False)
    credit_score = StringField(choices=REC.CREDIT_SCORE_REQ, required=False)
    utilities_included = StringField(choices=REC.UTILITIES, required=False)
    access_to_amenities = StringField(choices=REC.AMENITIES, required=False)
    additional_fees = StringField(choices=REC.ADDITIONAL_FEES, required=False)
    pet_policy = StringField(choices=REC.PET_POLICY, required=False)
    renters_insurance_requirement = StringField(
        choices=REC.RENTERS_INSURANCE, required=False
    )
    security_measures = StringField(
        choices=REC.SECURITY_MEASURE, required=False
    )

    # Land
    land_type = StringField(required=False)

    # commercial
    hoa_fees = IntField(min_value=1)
    number_of_floors = IntField(min_value=1, required=False)

    # Bedroom
    rent_price = StringField(required=False)
    security_deposit = IntField(min_value=1, required=False)
    house_rules = StringField(required=False)
    location_details = StringField(required=False)
    availability_dates = StringField(required=False)
    number_of_occupants = StringField(required=False)
    bathroom_type = StringField(choices=REC.BATHROOM_TYPE, required=False)
    kitchen_access_type = StringField(
        choices=REC.KITCHEN_ACCESS_TYPE, required=False
    )
    laundry_facilities = StringField(
        choices=REC.LAUNDRY_FACILITIES, required=False
    )
    bedroom_additional_Fees = StringField(
        choices=REC.BEDROOM_ADDITIONAL_FEES, required=False
    )
    smoking_policy = StringField(choices=REC.SMOKING_POLICY, required=False)
    security_features = StringField(
        choices=REC.SECURITY_FEATURES, required=False
    )
    preferred_occupants = StringField(
        choices=REC.PREFERRED_OCCUPANTS, required=False
    )

    # Business Checks
    from_business = BooleanField(required=False, default=False)
    listing_clicks = IntField(default=0, required=False)

    # Timestamps
    created_at = fields.DateTimeField()
    updated_at = fields.DateTimeField()

    # Status
    is_active = BooleanField(required=True, default=True)

    meta = {
        "collection": "real_estate_listing",
        "ordering": ["-created_at"],
        "indexes": [
            {"fields": ["title"]},
            {"fields": ["category"]},
            {"fields": ["subcategory"]},
        ],
    }
