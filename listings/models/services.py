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

from tokenize import String

from mongoengine import Document
from helpers.constants import ServicesConstants as SC
from mongoengine.fields import (
    IntField,
    StringField,
    ListField,
    BooleanField,
    DateTimeField,
    DecimalField,
    PointField,
)


class ServicesListing(Document):
    '''
    Service category listings.
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

    other = StringField(required=False)
    certifications = StringField(choices=SC.CERTIFICATION, required=False)
    service_fee = DecimalField(required=True)
    negotiable = StringField(choices=SC.NEGOTIABLE, required=False)

    # category based
    service_type = StringField(required=False)
    availability = IntField(required=True)
    pricing_structure = IntField(required=False)
    service_area = StringField(required=False)

    # Cleaning
    cleaning_type = StringField(required=False)
    insurance = StringField(choices=SC.INSURANCE, required=False)
    payment_options = StringField(choices=SC.PAYMENT_OPTION, required=False)
    cleaning_services = StringField(
        choices=SC.CLEANING_SERVICES, required=False
    )
    eco_friendly_product = StringField(
        choices=SC.ECO_FRIENDLY_PRODUCTS, required=False
    )
    provided_equipment = StringField(
        choices=SC.EQUIPMENT_PROVIDED, required=False
    )

    # Extra fields as per different subcategories
    # Handy man
    experience_qualifications = StringField(required=False)
    handyman_services = StringField(
        choices=SC.HANDYMAN_SPECIFIC_SERVICES, required=False
    )
    same_day_service = StringField(choices=SC.SAME_DAY_SERVICE, required=False)
    # Driver
    licence_type = StringField(required=False)
    insurance_bonding_status = StringField(required=False)
    additional_service = StringField(required=False)
    driving_services = StringField(choices=SC.DRIVING_SERVICES, required=False)
    vehicle_type = StringField(choices=SC.AVAILABLE_VEHICLES, required=False)
    # Landscaping
    landscaping_services = StringField(
        choices=SC.LANDSCAPING_SERVICES, required=False
    )
    regular_maintenance = StringField(
        choices=SC.REGULAR_MAINTENANCE, required=False
    )
    seasonal_service = StringField(choices=SC.SEASONAL_SERVICES, required=False)
    # Consultancy
    initial_consultation = StringField(
        choices=SC.SERVICE_AVAILABLE, required=False
    )
    consultancy_services = StringField(
        choices=SC.CONSULTANCY_SERVICES, required=False
    )
    offered_services = StringField(choices=SC.SERVICE_AVAILABLE, required=False)
    # Home automation
    automation_services = StringField(
        choices=SC.AUTOMATION_SERVICES, required=False
    )
    supported_products = StringField(required=False)
    # Classes and courses
    subject_skills = StringField(required=False)
    classes_format = StringField(choices=SC.CLASSES_FORMAT, required=False)
    class_duration = IntField(required=False)
    # Personal training
    training_services = StringField(choices=SC.TRAINING_OFFERED, required=False)
    session_format = StringField(choices=SC.SERVICE_AVAILABLE, required=False)
    personalised_fitness_plan = StringField(
        choices=SC.PERSONALISED_FITNESS_PLAN, required=False
    )
    group_session = StringField(choices=SC.GROUP_SESSION, required=False)
    # Construction
    construction_services = StringField(
        choices=SC.CONSTRUCTION_SERVICES, required=False
    )
    # Technology
    expertise_level = StringField(choices=SC.EXPERTISE_LEVEL, required=False)
    technology_services = StringField(
        choices=SC.TECHNOLOGY_SERVICES, required=False
    )
    service_delivery_method = StringField(
        choices=SC.DELIVERY_METHOD, required=False
    )
    # utilize: offered services in technology delivery method section
    ongoing_support_maintenance = StringField(
        choices=SC.ONGOING_SUPPORT, required=False
    )
    # Immigration and visa
    visa_services = StringField(choices=SC.VISA_SERVICES, required=False)
    free_appointment = StringField(choices=SC.FREE_APPOINTMENTS, required=False)
    # Event services
    portfolio = ListField(required=False)
    event_type = StringField(choices=SC.EVENT_TYPES, required=False)
    events_services = StringField(
        choices=SC.EVENT_SPECIFIC_SERVICES, required=False
    )
    customizable_package = StringField(
        choices=SC.CUSTOMIZABLE_PACKAGE, required=False
    )
    # Movers and packers
    movers_services = StringField(choices=SC.MOVING_SERVICE, required=False)
    packing_material = StringField(choices=SC.PACKING_MATERIALS, required=False)
    insurance_for_goods = StringField(
        choices=SC.GOODS_TRANSIT_INSURANCE, required=False
    )
    # Farm and fresh
    farm_services = StringField(choices=SC.PRODUCTS_AVAILABLE, required=False)
    delivery_availability = StringField(
        choices=SC.DELIVERY_AVAILABILITY, required=False
    )
    organic_sourced = StringField(choices=SC.ORGANIC_SOURCED, required=False)
    regular_delivery_option = StringField(
        choices=SC.REGULAR_DELIVERY_OPTION, required=False
    )
    # Video and photography
    photography_services = StringField(
        choices=SC.PHOTOGRAPHY_SERVICES, required=False
    )
    different_packages = StringField(
        choices=SC.DIFFERENT_PACKAGES, required=False
    )
    recurring_services = StringField(
        choices=SC.RECURRING_SERVICE_PLAN, required=False
    )
    # interior design
    interior_services = StringField(
        choices=SC.INTERIOR_DESIGN_SERVICES, required=False
    )
    material_furniture_Selection = StringField(
        choices=SC.FURNITURE_SELECTION, required=False
    )
    rendering_visualizations = StringField(
        choices=SC.RENDERING_VISUALIZING, required=False
    )
    # Homemade food
    service_availability = StringField(
        choices=SC.HOMEMADE_SERVICE, required=False
    )
    homemade_service = StringField(
        choices=SC.AVAILABLE_HOMEMADE_FOOD, required=False
    )
    # Insurance
    insurance_service = StringField(
        choices=SC.INSURANCE_SERVICES, required=False
    )
    # Home care
    homecare_service = StringField(
        choices=SC.HOME_CARE_SERVICES, required=False
    )

    # Catering
    cuisine_type = StringField(required=False)
    # Chef
    cuisine_speciality = StringField(required=False)
    # Influencer
    platform = StringField(required=False)
    audience_size = IntField(required=False)
    # Ac Services
    # todo check if specialization in personal training field also handle in this
    ac_Services = StringField(required=False)
    brands_specialization = StringField(required=False)
    # cake
    cake_type = StringField(required=False)
    # finger food
    menu = StringField(required=False)
    # buffet
    menu_customization = StringField(
        choices=SC.MENU_CUSTOMIZATION, required=False
    )
    # Transport service
    distance = StringField(required=False)
    transport_type = StringField(required=False)

    # Business Checks
    from_business = BooleanField(required=False, default=False)
    listing_clicks = IntField(default=0, required=False)

    # Timestamps
    created_at = DateTimeField()
    updated_at = DateTimeField()

    # Status
    is_active = BooleanField(required=True, default=True)

    meta = {
        'collection': 'services_listing',
        'ordering': ['-created_at'],
        'indexes': [
            {'fields': ['title']},
            {'fields': ['category']},
            {'fields': ['subcategory']},
        ],
    }
