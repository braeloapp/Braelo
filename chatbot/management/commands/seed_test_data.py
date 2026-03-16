"""
Seed test user and businesses with static location (lat/lng, state, county, zip) for testing.
Run: python manage.py seed_test_data

Use user_id or session_id "test-user" in /api/chat to get proper RAG and business responses.
"""
from decimal import Decimal
from django.core.management.base import BaseCommand
from chatbot.models import User as ChatUser, AdPackage, Business


# Phoenix, AZ area - test user and businesses
TEST_USER_ID = "test-user"
TEST_STATE = "Arizona"
TEST_COUNTY = "Maricopa"
TEST_ZIP = "85001"
TEST_CITY = "Phoenix"
USER_LAT = Decimal("33.4484")
USER_LON = Decimal("-112.0740")


def run_seed():
    user, created = ChatUser.objects.update_or_create(
        external_id=TEST_USER_ID,
        defaults={
            "language_preference": "en",
            "state": TEST_STATE,
            "city": TEST_CITY,
            "county": TEST_COUNTY,
            "zip_code": TEST_ZIP,
            "location_enabled": True,
            "latitude": USER_LAT,
            "longitude": USER_LON,
        },
    )
    action = "Created" if created else "Updated"
    yield f"  {action} test user: external_id={TEST_USER_ID}, state={TEST_STATE}, county={TEST_COUNTY}, zip={TEST_ZIP}, lat/lng set"

    pkg, _ = AdPackage.objects.get_or_create(
        name="Premium",
        defaults={"priority": 10, "max_impressions": 500},
    )
    yield f"  Ad package: {pkg.name} (priority={pkg.priority})"

    businesses_data = [
        {
            "name": "Desert Legal Group",
            "category": "legal",
            "subcategory": "lawyer",
            "state": TEST_STATE,
            "city": TEST_CITY,
            "county": TEST_COUNTY,
            "zip_code": "85001",
            "latitude": Decimal("33.4490"),
            "longitude": Decimal("-112.0730"),
            "languages": "en,es",
            "contact_info": "602-555-0100",
            "whatsapp_url": "https://wa.me/16025550100",
            "ad_package": pkg,
            "impression_cap": 500,
            "impressions_used": 0,
        },
        {
            "name": "Sun Valley Tax Services",
            "category": "tax",
            "subcategory": "tax_preparer",
            "state": TEST_STATE,
            "city": TEST_CITY,
            "county": TEST_COUNTY,
            "zip_code": "85002",
            "latitude": Decimal("33.4550"),
            "longitude": Decimal("-112.0680"),
            "languages": "en,es,pt",
            "contact_info": "602-555-0200",
            "whatsapp_url": "https://wa.me/16025550200",
            "ad_package": None,
            "impression_cap": 1000,
            "impressions_used": 0,
        },
        {
            "name": "Phoenix Immigration Help",
            "category": "immigration",
            "subcategory": "consultant",
            "state": TEST_STATE,
            "city": "Phoenix",
            "county": TEST_COUNTY,
            "zip_code": "85003",
            "latitude": Decimal("33.4460"),
            "longitude": Decimal("-112.0760"),
            "languages": "en,es",
            "contact_info": "602-555-0300",
            "whatsapp_url": "",
            "ad_package": None,
            "impression_cap": 1000,
            "impressions_used": 0,
        },
        {
            "name": "Maricopa Real Estate",
            "category": "housing",
            "subcategory": "real_estate_agent",
            "state": TEST_STATE,
            "city": TEST_CITY,
            "county": TEST_COUNTY,
            "zip_code": "85004",
            "latitude": Decimal("33.4520"),
            "longitude": Decimal("-112.0700"),
            "languages": "en,es,pt",
            "contact_info": "602-555-0400",
            "whatsapp_url": "https://wa.me/16025550400",
            "ad_package": None,
            "impression_cap": 1000,
            "impressions_used": 0,
        },
    ]

    for i, data in enumerate(businesses_data):
        name = data.pop("name")
        b, created = Business.objects.update_or_create(
            name=name,
            defaults={**data, "is_active": True, "is_banned": False},
        )
        action = "Created" if created else "Updated"
        yield f"  {action} business: {b.name} ({b.category}, {b.city}, {b.state})"

    yield ""
    yield "Use in API: user_id or session_id = 'test-user' (or send state, county, zip_code in body)."
    yield "Example: POST /chatbot/api/chat with body: {\"message\": \"Find me a lawyer\", \"user_id\": \"test-user\"}"


class Command(BaseCommand):
    help = "Seed test user and businesses with static location for testing chat and business matching"

    def handle(self, *args, **options):
        self.stdout.write("Seeding test data (user + businesses in Arizona/Maricopa/Phoenix)...")
        for line in run_seed():
            self.stdout.write(line)
        self.stdout.write(self.style.SUCCESS("Done. You can now test with user_id=test-user."))
