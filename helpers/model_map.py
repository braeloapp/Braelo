'''
---------------------------------------------------
Project:        Braelo
Date:           April 28, 2025
Author:         Faizan
---------------------------------------------------

Description:
Model Map file.
---------------------------------------------------
'''

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
