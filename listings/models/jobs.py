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

from mongoengine import fields, Document
from mongoengine.fields import (
    IntField,
    StringField,
    ListField,
    BooleanField,
    PointField,
)

from helpers import JobsConstants as JC


class JobsListing(Document):
    '''
    Jobs category listings.
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
    job_tittle = StringField(required=True)
    required_skills = StringField(required=True)
    experience_level = StringField(required=True)
    employment_type = StringField(required=True)

    salary_range = StringField(required=True)
    negotiable = StringField(choices=JC.NEGOTIABLE, required=True)

    # Full time
    working_hours = IntField(required=False)
    benefits_offered = StringField(required=False)
    work_permit = StringField(choices=JC.WORK_PERMIT, required=False)

    # Part-time
    flexibility = IntField(required=False)

    # freelancer
    project_type = StringField(required=False)
    contract_duration = IntField(required=False)

    # Home offices
    remote_work_tools = StringField(required=False)

    # Helper
    service_type = StringField(required=False)
    duties = StringField(required=False)
    accommodation_provided = StringField(required=False)
    own_tools = StringField(choices=JC.HELPER_TOOLS, required=False)
    car_needed = StringField(choices=JC.HELPER_CAR, required=False)
    helper_pay = StringField(choices=JC.HELPER_PAY, required=False)

    # Business Checks
    from_business = BooleanField(required=False, default=False)
    listing_clicks = IntField(default=0, required=False)

    # Timestamps
    created_at = fields.DateTimeField()
    updated_at = fields.DateTimeField()

    # Status
    is_active = BooleanField(required=True, default=True)

    meta = {
        'collection': 'jobs_listing',
        'ordering': ['-created_at'],
        'indexes': [
            {'fields': ['title']},
            {'fields': ['category']},
            {'fields': ['subcategory']},
        ],
    }
