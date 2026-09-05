from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from helpers.normalize import resolve_subcategory
from listings.api.fetch_listings import Recent, Recommendations
from listings.api.search import Search
from listings.field_contract import apply_field_aliases, extract_coordinates
from listings.geo import parse_coordinates, parse_radius_meters
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


class GeoHelperTests(TestCase):
    def test_parse_coordinates_accepts_lng_lat_json(self):
        self.assertEqual(parse_coordinates('[74.28, 31.45]'), (74.28, 31.45))

    def test_parse_coordinates_blank_is_none(self):
        self.assertIsNone(parse_coordinates(None))
        self.assertIsNone(parse_coordinates(''))
        self.assertIsNone(parse_coordinates('   '))

    def test_parse_coordinates_rejects_bool_and_out_of_range(self):
        with self.assertRaises(ValidationError):
            parse_coordinates('[true, 31.45]')
        with self.assertRaises(ValidationError):
            parse_coordinates('[200, 31.45]')
        with self.assertRaises(ValidationError):
            parse_coordinates('not-json')

    @override_settings(
        LISTING_RADIUS_M=10000,
        LISTING_RADIUS_MIN_M=500,
        LISTING_RADIUS_MAX_M=100000,
    )
    def test_parse_radius_default_and_bounds(self):
        self.assertEqual(parse_radius_meters(None), 10000)
        self.assertEqual(parse_radius_meters('25000'), 25000)
        with self.assertRaises(ValidationError):
            parse_radius_meters('100')
        with self.assertRaises(ValidationError):
            parse_radius_meters('999999')
        with self.assertRaises(ValidationError):
            parse_radius_meters('wide')


class RecommendationInterestTests(TestCase):
    def _request(self, authenticated=True, user_id=9, params=None):
        params = params or {}
        request = MagicMock()
        request.user.is_authenticated = authenticated
        request.user.id = user_id
        request.GET.get.side_effect = lambda key, default=None: params.get(
            key, default
        )
        return request

    @patch('listings.api.fetch_listings.get_user_recommendations')
    @patch('listings.api.fetch_listings.ListSync')
    def test_interests_apply_when_coordinates_present(
        self, mock_sync, mock_interests
    ):
        mock_interests.return_value = ['Vehicles', 'Cars']
        geo_qs = MagicMock()
        interest_qs = MagicMock()
        mock_sync.objects.filter.return_value = geo_qs
        geo_qs.filter.return_value = interest_qs

        view = Recommendations()
        view.request = self._request(
            params={'listing_coordinates': '[74.3, 31.5]'}
        )
        queryset = view.get_queryset()

        self.assertIs(queryset, interest_qs)
        kwargs = mock_sync.objects.filter.call_args.kwargs
        self.assertTrue(kwargs.get('is_active'))
        self.assertEqual(kwargs.get('listing_coordinates__near'), [74.3, 31.5])
        self.assertEqual(kwargs.get('listing_coordinates__max_distance'), 10000)
        geo_qs.filter.assert_called_once()

    @patch('listings.api.fetch_listings.get_user_recommendations')
    @patch('listings.api.fetch_listings.ListSync')
    def test_interests_apply_without_coordinates(
        self, mock_sync, mock_interests
    ):
        mock_interests.return_value = ['kids']
        base_qs = MagicMock()
        interest_qs = MagicMock()
        mock_sync.objects.filter.return_value = base_qs
        base_qs.filter.return_value = interest_qs

        view = Recommendations()
        view.request = self._request()
        queryset = view.get_queryset()

        mock_sync.objects.filter.assert_called_with(is_active=True)
        self.assertIs(queryset, interest_qs)


class RecentGeoTests(TestCase):
    @patch('listings.api.fetch_listings.ListSync')
    def test_empty_coordinates_do_not_use_geo_query(self, mock_sync):
        filtered = MagicMock()
        mock_sync.objects.filter.return_value = filtered
        view = Recent()
        request = MagicMock()
        request.GET.get.return_value = ''
        view.request = request

        queryset = view.get_queryset()

        mock_sync.objects.filter.assert_called_with(is_active=True)
        self.assertIs(queryset, filtered)

    @patch('listings.api.fetch_listings.ListSync')
    def test_recent_uses_requested_radius(self, mock_sync):
        filtered = MagicMock()
        mock_sync.objects.filter.return_value = filtered
        view = Recent()
        request = MagicMock()
        request.GET.get.side_effect = lambda key, default=None: {
            'listing_coordinates': '[74.3, 31.5]',
            'radius': '25000',
        }.get(key, default)
        view.request = request

        view.get_queryset()
        kwargs = mock_sync.objects.filter.call_args.kwargs
        self.assertEqual(kwargs.get('listing_coordinates__max_distance'), 25000)
        self.assertTrue(kwargs.get('is_active'))


class SearchQueryTests(TestCase):
    def _request(self, params, authenticated=False):
        request = MagicMock()
        request.user.is_authenticated = authenticated
        request.user.id = 3
        request.GET.get.side_effect = lambda key, default=None: params.get(
            key, default
        )
        return request

    @patch('listings.api.search.ListSync')
    def test_search_requires_three_characters(self, _mock_sync):
        view = Search()
        view.request = self._request({'search': 'ab'})
        with self.assertRaises(ValidationError):
            view.get_queryset()

    @patch('listings.api.search.User')
    @patch('listings.api.search.ListSync')
    def test_search_filters_active_and_text(self, mock_sync, mock_user):
        base_qs = MagicMock()
        text_qs = MagicMock()
        mock_sync.objects.filter.return_value = base_qs
        base_qs.filter.return_value = text_qs

        view = Search()
        view.request = self._request({'search': 'honda'})
        queryset = view.get_queryset()

        mock_sync.objects.filter.assert_called_with(is_active=True)
        self.assertIs(queryset, text_qs)
        mock_user.objects.filter.assert_not_called()

    @patch('listings.api.search.User')
    @patch('listings.api.search.ListSync')
    def test_search_applies_geo_and_category(self, mock_sync, mock_user):
        base_qs = MagicMock()
        text_qs = MagicMock()
        category_qs = MagicMock()
        mock_sync.objects.filter.return_value = base_qs
        base_qs.filter.return_value = text_qs
        text_qs.filter.return_value = category_qs

        view = Search()
        view.request = self._request(
            {
                'search': 'honda',
                'category': 'Vehicles',
                'listing_coordinates': '[74.3, 31.5]',
            }
        )
        queryset = view.get_queryset()

        kwargs = mock_sync.objects.filter.call_args.kwargs
        self.assertTrue(kwargs.get('is_active'))
        self.assertEqual(kwargs.get('listing_coordinates__near'), [74.3, 31.5])
        text_qs.filter.assert_called_with(category='Vehicles')
        self.assertIs(queryset, category_qs)
        mock_user.objects.filter.assert_not_called()


class FlipListingIdempotencyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="flipper@example.com",
            email="flipper@example.com",
            name="Flipper",
            password="pass12345",
            is_email_verified=True,
            listings_count=1,
        )
        self.client = APIClient()
        token = str(RefreshToken.for_user(self.user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    @patch("listings.api.saved_listing.upsert_listing_directory_doc")
    @patch("listings.api.saved_listing.ListSynchronize")
    @patch("listings.api.saved_listing.MODEL_MAP")
    def test_repeat_flip_does_not_increment_count(
        self, mock_map, mock_sync, _mock_upsert
    ):
        listing = MagicMock()
        listing.user_id = self.user.id
        listing.is_active = True
        model = MagicMock()
        model.objects.filter.return_value.first.return_value = listing
        mock_map.__contains__.return_value = True
        mock_map.__getitem__.return_value = model
        mock_sync.flip_status.return_value = False

        with patch(
            "listings.api.saved_listing.resolve_category",
            return_value="Vehicles",
        ):
            first = self.client.post(
                "/listing/flip/status",
                data={
                    "listing_id": "507f1f77bcf86cd799439011",
                    "category": "Vehicles",
                    "status": True,
                },
                format="json",
            )
            second = self.client.post(
                "/listing/flip/status",
                data={
                    "listing_id": "507f1f77bcf86cd799439011",
                    "category": "Vehicles",
                    "status": True,
                },
                format="json",
            )

        self.assertEqual(first.json().get("status"), 200)
        self.assertEqual(second.json().get("status"), 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.listings_count, 1)

    def test_listsync_flip_is_idempotent(self):
        from helpers.listsync import ListSynchronize

        listing = MagicMock()
        listing.is_active = True
        model = MagicMock()
        model.objects.return_value.first.return_value = listing

        changed = ListSynchronize.flip_status(
            listing_id="abc",
            status=True,
            user_id=1,
            model=model,
        )
        self.assertFalse(changed)
        model.objects.return_value.update_one.assert_not_called()
