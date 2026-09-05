from unittest.mock import MagicMock, patch

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from helpers.normalize import resolve_subcategory
from listings.api.fetch_listings import Recommendations
from listings.field_contract import apply_field_aliases, extract_coordinates
from users.models import User


class UnsaveListingAuthorizationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="saver@example.com",
            email="saver@example.com",
            name="Saver",
            password="pass12345",
            is_email_verified=True,
        )
        self.client = APIClient()
        token = str(RefreshToken.for_user(self.user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    @patch("listings.api.saved_listing.SavedItem")
    def test_unsave_filters_by_authenticated_user(self, mock_saved):
        queryset = MagicMock()
        queryset.delete.return_value = 1
        mock_saved.objects.filter.return_value = queryset

        response = self.client.post(
            "/listing/save?save=False",
            data={"listing_id": "507f1f77bcf86cd799439011"},
            format="json",
        )
        body = response.json()
        self.assertEqual(body.get("status"), 200)
        kwargs = mock_saved.objects.filter.call_args.kwargs
        self.assertEqual(kwargs.get("user_id"), self.user.id)
        self.assertEqual(kwargs.get("listing_id"), "507f1f77bcf86cd799439011")


class SportsSubcategoryAliasTests(TestCase):
    def test_sports_activities_alias(self):
        self.assertEqual(
            resolve_subcategory('sportsandhobby', 'activities'),
            'outdooractivities',
        )
        self.assertEqual(
            resolve_subcategory('sportsandhobby', 'Outdoor Activities'),
            'outdooractivities',
        )

    def test_kids_activities_unchanged(self):
        self.assertEqual(resolve_subcategory('kids', 'activities'), 'activities')


class ListingFieldContractTests(TestCase):
    def test_vehicle_key_and_chip_aliases(self):
        payload = apply_field_aliases(
            {
                'loadcapcity': '1000',
                'partname': 'filter',
                'fuelType': 'Petrol',
                'Transmission': 'Automatic',
                'Purpose': 'Sale',
                'Number of Doors': '4',
                'For Sale': 'Yes',
                'location': 'Lahore Canal',
            },
            subcategory='Cars',
        )
        self.assertEqual(payload['Load_capacity'], '1000')
        self.assertEqual(payload['part_name'], 'filter')
        self.assertEqual(payload['fuel_type'], 'Petrol')
        self.assertEqual(payload['transmission'], 'AUTOMATIC')
        self.assertEqual(payload['purpose'], 'SALE')
        self.assertEqual(payload['number_of_doors'], '4/5')
        self.assertEqual(payload['for_sale'], 'YES')
        self.assertEqual(payload['location'], 'Lahore Canal')

    def test_van_and_boat_length_aliases(self):
        van = apply_field_aliases({'length': '8'}, subcategory='Van')
        boat = apply_field_aliases({'length': '12'}, subcategory='Boat')
        self.assertEqual(van['passenger_capacity'], '8')
        self.assertEqual(boat['boat_length'], '12')

    def test_outdoor_activity_field_alias(self):
        payload = apply_field_aliases(
            {'processor': 'hiking'}, subcategory='outdooractivities'
        )
        self.assertEqual(payload['activity_type'], 'hiking')

    def test_extract_geojson_coordinates(self):
        self.assertEqual(
            extract_coordinates(
                {'type': 'Point', 'coordinates': [74.28, 31.45]}
            ),
            [74.28, 31.45],
        )
        self.assertEqual(extract_coordinates([74.28, 31.45]), [74.28, 31.45])


class AnonymousRecommendationTests(TestCase):
    @patch('listings.api.fetch_listings.get_user_recommendations', return_value=[])
    @patch('listings.api.fetch_listings.ListSync')
    def test_anonymous_recommendations_filter_active_only(
        self, mock_sync, _mock_interests
    ):
        filtered = MagicMock()
        mock_sync.objects.filter.return_value = filtered
        view = Recommendations()
        request = MagicMock()
        request.user.is_authenticated = False
        request.GET.get.return_value = None
        view.request = request

        queryset = view.get_queryset()

        mock_sync.objects.filter.assert_called_with(is_active=True)
        mock_sync.objects.all.assert_not_called()
        self.assertIs(queryset, filtered)
