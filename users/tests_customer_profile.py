from unittest.mock import MagicMock, patch

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import User
from users.services.customer_profile import build_customer_profile


class CustomerProfileServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            username='customer-profile',
            name='Criss Germano',
            password='x',
            role='Client',
            city='Boca Raton',
            state='FL',
            is_phone_verified=True,
        )

    @patch('users.services.customer_profile._count_events', return_value=12)
    @patch('users.services.customer_profile.SavedItem')
    @patch('users.services.customer_profile.ListSync')
    def test_build_customer_profile_counts(self, mock_sync, mock_saved, _views):
        listing_qs = MagicMock()
        listing_qs.count.side_effect = [4, 3, 1]
        mock_sync.objects.filter.return_value = listing_qs
        mock_saved.objects.filter.return_value.count.return_value = 12

        payload = build_customer_profile(self.user)

        self.assertEqual(payload['name'], 'Criss Germano')
        self.assertEqual(payload['location'], 'Boca Raton, FL')
        self.assertTrue(payload['is_phone_verified'])
        self.assertEqual(payload['listings']['total'], 4)
        self.assertEqual(payload['listings']['active'], 3)
        self.assertEqual(payload['listings']['pending'], 1)
        self.assertEqual(payload['saved']['listings'], 12)
        self.assertEqual(payload['saved']['businesses'], 0)
        self.assertEqual(payload['views']['last_30d'], 12)

    def test_unauthenticated_customer_profile_rejected(self):
        client = APIClient()
        response = client.get('/auth/customer_profile')
        self.assertIn(response.status_code, (401, 403))

    @patch('users.api.profile.build_customer_profile')
    def test_authenticated_customer_profile(self, mock_build):
        mock_build.return_value = {
            'name': 'Criss Germano',
            'listings': {'total': 3, 'active': 3, 'pending': 0},
            'saved': {'listings': 12, 'businesses': 0},
            'views': {'last_30d': 10},
        }
        client = APIClient()
        token = str(RefreshToken.for_user(self.user).access_token)
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        response = client.get('/auth/customer_profile')
        body = response.json()
        self.assertEqual(body.get('status'), 200)
        self.assertEqual(body['data']['saved']['listings'], 12)
        mock_build.assert_called_once()
