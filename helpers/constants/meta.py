# Subcategories — client taxonomy + Services (includes gastronomy for **business** listings)

VEHICLES = [
    "Cars",
    "Motorcycle",
    "Truck",
    "Bike",
    "Boat",
    "Van",
    "Scooter",
    "partsandaccessories",
    "Rentals",
]

REAL_ESTATE = [
    "House",
    "Apartment",
    "Land",
    "mobilehome",
    "commercial",
    "bedroom",
    "suite",
    "studio",
    "vacationhome",
    "basement",
]

ELECTRONICS = [
    "smartphones",
    "computers",
    "appliances",
    "games",
    "servicesandparts",
]

EVENTS = [
    "networkingevents",
    "concert",
    "festival",
]

JOBS = [
    "fulltime",
    "parttime",
    "freelancer",
    "helper",
    "homeoffice",
]

FURNITURE = [
    "couch",
    "tables",
    "chairs",
    "beds",
    "customfurniture",
]

FASHION = [
    "clothes",
    "shoes",
    "accessories",
    "beautyproducts",
    "jewelry",
]

KIDS = [
    "health",
    "toys",
    "transport",
    "accessories",
    "classes",
    "babysitter",
    "daycare",
    "schooloffices",
    "afterschoolprogram",
    "activities",
]

SPORTS_HOBBY = [
    "sportsequipment",
    "musicalinstruments",
    "collecteditems",
    "games",
    "camping",
    "outdooractivities",
]

# Gastronomy subcategories live under **Services** (same as listings model + business client data)
RESTAURANT_SUBCATEGORIES = [
    "restaurants",
    "food",
    "cafe",
    "bar",
    "bakery",
    "fastfood",
    "pizza",
    "bbq",
    "buffet",
    "churrascaria",
    "dining",
    "fine_dining",
    "foodtruck",
]

SERVICES_CORE = [
    "Cleaning",
    "Handyman",
    "Drivers",
    "Landscaping",
    "Consultancy",
    "Home Automation",
    "Classes & Courses",
    "Personal Training",
    "Construction",
    "Technology",
    "Immigration and Visa",
    "Event Services",
    "Movers & Packers",
    "Farm & Fresh Food",
    "Video & Photography",
    "Interior Design",
    "Homemade Food",
    "Insurance Services",
    "Home Care (Health)",
    "Catering",
    "Chef",
    "Influencer",
    "AC Services",
    "Personal Trainer",
    "Cake",
    "Finger Food",
    "Buffet",
    "Transport Services",
]

# Single ordered list: services + restaurant slugs (deduped) for Business + listings validation
SERVICES = list(dict.fromkeys(list(SERVICES_CORE) + list(RESTAURANT_SUBCATEGORIES)))


CATEGORIES = {
    "Vehicles": VEHICLES,
    "Services": SERVICES,
    "realestate": REAL_ESTATE,
    "electronics": ELECTRONICS,
    "events": EVENTS,
    "jobs": JOBS,
    "furniture": FURNITURE,
    "fashion": FASHION,
    "kids": KIDS,
    "sportsandhobby": SPORTS_HOBBY,
}

CONFIRMATION = ["YES", "NO"]

USER_LISTINGS_THRESHOLD = 10
KEYWORDS_LIMIT = 10
LISTING_UPPER_THRESHOLD = 10
