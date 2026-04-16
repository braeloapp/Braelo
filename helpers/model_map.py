'''
---------------------------------------------------
Project:        Braelo
Date:           April 28, 2025
Author:         Faizan
---------------------------------------------------

Description:
Model Map file. Keys must match helpers.constants.CATEGORIES.
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
    "Vehicles": VehicleListing,
    "Services": ServicesListing,
    "realestate": RealEstateListing,
    "electronics": ElectronicsListing,
    "events": EventsListing,
    "jobs": JobsListing,
    "furniture": FurnitureListing,
    "fashion": FashionListing,
    "kids": KidsListing,
    "sportsandhobby": SportsHobbyListing,
}
