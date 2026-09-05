from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import User
from users.services.business_analytics import (
    bucket_datetimes,
    build_month_axis,
    change_payload,
    parse_period_days,
    percent_change,
    record_event,
)
from users.services.business_settings import (
    _clean_text,
    maybe_send_business_welcome,
)


class AnalyticsHelperTests(TestCase):
    def test_parse_period_days_clamps(self):
        self.assertEqual(parse_period_days('90'), 90)
        self.assertEqual(parse_period_days('bad'), 90)
        self.assertEqual(parse_period_days('0'), 90)
        self.assertEqual(parse_period_days('9999'), 365)

    def test_percent_change(self):
        self.assertEqual(percent_change(20, 10), 100.0)
        self.assertEqual(percent_change(5, 10), -50.0)
        self.assertEqual(percent_change(0, 0), 0.0)
        self.assertEqual(percent_change(4, 0), 100.0)

    def test_change_payload(self):
        payload = change_payload(12, 8)
        self.assertEqual(payload['previous'], 8)
        self.assertEqual(payload['percent'], 50.0)

    def test_month_axis_and_buckets(self):
        now = datetime(2026, 9, 5, 12, 0, tzinfo=dt_timezone.utc)
        labels, starts = build_month_axis(now, 3)
        self.assertEqual(labels, ['Jul', 'Aug', 'Sep'])
        self.assertEqual(len(starts), 3)
        values = [
            datetime(2026, 7, 10, tzinfo=dt_timezone.utc),
            datetime(2026, 9, 1, tzinfo=dt_timezone.utc),
            datetime(2026, 9, 4, tzinfo=dt_timezone.utc),
        ]
        self.assertEqual(bucket_datetimes(values, starts, now), [1, 0, 2])


class AnalyticsEventTests(TestCase):
    @patch('users.models.analytics_event.BusinessAnalyticsEvent')
    def test_record_event_skips_self(self, mock_event):
        result = record_event(12, 'view', listing_id='abc', actor_id=12)
        self.assertIsNone(result)
        mock_event.assert_not_called()

    @patch('users.models.analytics_event.BusinessAnalyticsEvent')
    def test_record_event_rejects_unknown_type(self, mock_event):
        self.assertIsNone(record_event(12, 'hack'))
        mock_event.assert_not_called()


class BusinessSettingsHelperTests(TestCase):
    def test_clean_text_requires_and_limits(self):
        self.assertEqual(_clean_text('  hi  ', 'body', required=True), 'hi')
        with self.assertRaises(ValidationError):
            _clean_text('   ', 'shortcut', required=True)
        with self.assertRaises(ValidationError):
            _clean_text('x' * 2001, 'body')

    @patch('users.services.business_settings.Business')
    @patch('users.services.business_settings.BusinessSettings')
    @patch('chats.models.Message')
    def test_welcome_sends_from_business_peer(
        self, mock_message, mock_settings, mock_business
    ):
        chat = SimpleNamespace(participants=['12', '44'])
        mock_business.objects.return_value.first.return_value = SimpleNamespace(
            user_id=44
        )
        mock_settings.objects.return_value.first.return_value = SimpleNamespace(
            welcome_enabled=True,
            welcome_message='Welcome to the shop',
        )
        saved = SimpleNamespace(id='m1')
        mock_message.return_value = saved
        saved.save = MagicMock()

        result = maybe_send_business_welcome(chat, '12')
        self.assertIs(result, saved)
        mock_message.assert_called()
        kwargs = mock_message.call_args.kwargs
        self.assertEqual(kwargs['sender_id'], '44')
        self.assertEqual(kwargs['content'], 'Welcome to the shop')

    @patch('users.services.business_settings.Business')
    @patch('users.services.business_settings.BusinessSettings')
    @patch('chats.models.Message')
    def test_welcome_skips_when_disabled(
        self, mock_message, mock_settings, mock_business
    ):
        chat = SimpleNamespace(participants=['12', '44'])
        mock_business.objects.return_value.first.return_value = SimpleNamespace(
            user_id=44
        )
        mock_settings.objects.return_value.first.return_value = SimpleNamespace(
            welcome_enabled=False,
            welcome_message='Hello',
        )
        self.assertIsNone(maybe_send_business_welcome(chat, '12'))
        mock_message.assert_not_called()


class BusinessDashboardApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='biz@example.com',
            email='biz@example.com',
            name='Biz',
            password='pass12345',
            is_email_verified=True,
            is_business=True,
            listings_clicks=4,
            business_featured=0,
        )
        self.client = APIClient()
        token = str(RefreshToken.for_user(self.user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    def test_dashboard_requires_auth(self):
        anon = APIClient()
        response = anon.get('/auth/business/dashboard')
        self.assertEqual(response.status_code, 401)

    @patch('users.api.business.build_business_dashboard')
    def test_dashboard_uses_authenticated_user(self, mock_build):
        mock_build.return_value = {
            'Clicks': 4,
            'Interactions': 2,
            'Listing': 1,
            'Featured': 0,
            'series': {'labels': ['Jul'], 'views': [0], 'messages': [1], 'listings': [1]},
        }
        response = self.client.get('/auth/business/dashboard?period=30')
        body = response.json()
        self.assertEqual(body.get('status'), 200)
        self.assertEqual(body['data']['Clicks'], 4)
        mock_build.assert_called_once()
        self.assertEqual(mock_build.call_args[0][0].id, self.user.id)
        self.assertEqual(mock_build.call_args[0][1], 30)

    def test_dashboard_rejects_personal_account(self):
        self.user.is_business = False
        self.user.save(update_fields=['is_business'])
        response = self.client.get('/auth/business/dashboard')
        self.assertEqual(response.json().get('status'), 400)


class BusinessSettingsApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='settings@example.com',
            email='settings@example.com',
            name='Settings',
            password='pass12345',
            is_email_verified=True,
            is_business=True,
        )
        self.other = User.objects.create_user(
            username='other@example.com',
            email='other@example.com',
            name='Other',
            password='pass12345',
            is_email_verified=True,
            is_business=True,
        )
        self.client = APIClient()
        token = str(RefreshToken.for_user(self.user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    def test_settings_require_auth(self):
        anon = APIClient()
        response = anon.get('/auth/business/settings')
        self.assertEqual(response.status_code, 401)

    @patch('users.api.business_settings.require_owned_business')
    @patch('users.api.business_settings.get_or_create_settings')
    def test_get_settings_uses_caller(self, mock_get, mock_require):
        settings = SimpleNamespace(
            to_public_dict=lambda: {
                'user_id': self.user.id,
                'welcome_message': 'Hi',
                'welcome_enabled': True,
                'response_suggestions_enabled': False,
                'saved_replies': [],
            }
        )
        mock_get.return_value = settings
        response = self.client.get('/auth/business/settings')
        body = response.json()
        self.assertEqual(body.get('status'), 200)
        self.assertEqual(body['data']['user_id'], self.user.id)
        mock_require.assert_called_once()
        mock_get.assert_called_once_with(self.user.id)

    @patch('users.api.business_settings.update_settings')
    def test_put_settings_uses_caller(self, mock_update):
        mock_update.return_value = SimpleNamespace(
            to_public_dict=lambda: {
                'user_id': self.user.id,
                'welcome_message': 'Hello',
                'welcome_enabled': True,
                'response_suggestions_enabled': True,
                'saved_replies': [],
            }
        )
        response = self.client.put(
            '/auth/business/settings',
            {
                'welcome_message': 'Hello',
                'welcome_enabled': True,
                'response_suggestions_enabled': True,
            },
            format='json',
        )
        self.assertEqual(response.json().get('status'), 200)
        self.assertEqual(mock_update.call_args[0][0].id, self.user.id)

    @patch('users.api.business_settings.add_saved_reply')
    def test_create_saved_reply_uses_caller(self, mock_add):
        reply = SimpleNamespace(to_public_dict=lambda: {'reply_id': 'r1'})
        settings = SimpleNamespace(
            to_public_dict=lambda: {'saved_replies': [{'reply_id': 'r1'}]}
        )
        mock_add.return_value = (settings, reply)
        response = self.client.post(
            '/auth/business/saved-replies',
            {'shortcut': 'hours', 'body': 'We open at 9'},
            format='json',
        )
        self.assertEqual(response.json().get('status'), 201)
        self.assertEqual(mock_add.call_args[0][0].id, self.user.id)


class AdminStatisticsApiTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            username='admin@example.com',
            email='admin@example.com',
            name='Admin',
            password='pass12345',
            is_staff=True,
            is_email_verified=True,
        )
        self.user = User.objects.create_user(
            username='plain@example.com',
            email='plain@example.com',
            name='Plain',
            password='pass12345',
            is_email_verified=True,
        )
        self.client = APIClient()
        token = str(RefreshToken.for_user(self.staff).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    def test_statistics_require_staff(self):
        client = APIClient()
        token = str(RefreshToken.for_user(self.user).access_token)
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        response = client.get('/admin-panel/statistics')
        self.assertIn(response.status_code, (403, 401))

    @patch('admin_panel.api.statistics.build_admin_statistics')
    def test_statistics_payload(self, mock_build):
        mock_build.return_value = {
            'users': {'total': 2, 'active': 2, 'new_7d': 1, 'new_today': 0},
            'businesses': {'total': 1, 'active': 1},
            'listings': {'total': 3, 'active': 2, 'inactive': 1, 'by_category': {}},
            'reports': {'total': 0},
            'support_requests': {'total': 0, 'open': 0},
            'messages': {'total': 0, 'conversations': 0},
            'engagement': {'listing_clicks': 0},
            'growth': {'labels': ['Sep'], 'users': [1], 'businesses': [0], 'listings': [0]},
            'recent_active_users': [],
        }
        response = self.client.get('/admin-panel/statistics')
        body = response.json()
        self.assertEqual(body.get('status'), 200)
        self.assertEqual(body['data']['users']['total'], 2)
        mock_build.assert_called_once()
