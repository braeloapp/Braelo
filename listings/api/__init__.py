'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
__init__.py file for endpoints imports.
---------------------------------------------------
'''

from listings.api.category import *
from .update_listing import *
from .fetch_listings import *
from .saved_listing import *
from listings.models import (
    VehicleListing,
    RealEstateListing,
    ServicesListing,
    EventsListing,
    JobsListing,
    ElectronicsListing,
    FurnitureListing,
    FashionListing,
    KidsListing,
    SportsHobbyListing,
)

MODEL_MAP = {
    'Vehicles': VehicleListing,
    'Real Estate': RealEstateListing,
    'Services': ServicesListing,
    'Events': EventsListing,
    'Jobs': JobsListing,
    'Electronics': ElectronicsListing,
    'Furniture': FurnitureListing,
    'Fashion': FashionListing,
    'Kids': KidsListing,
    'Sports & Hobby': SportsHobbyListing,
}
