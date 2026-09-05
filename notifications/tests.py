from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.urls import resolve
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from helpers.notifications import (
    business_created_event,
    chat_message_event,
    listing_created_event,
    listing_saved_event,
    support_reply_event,
)
from notifications.api.operations import _user_can_access
from notifications.services.email import EmailTemplateService
from notifications.services.preferences import (
    EVENT_TO_PREFERENCE,
    is_preference_enabled,
    upsert_preferences,
)
from users.models import User


class NotificationPayloadTests(TestCase):
    def test_listing_saved_uses_structured_data(self):
        payload = listing_saved_event(9, 'abc')
        self.assertEqual(payload['type'], 'listing')
        self.assertEqual(payload['data']['type'], 'listing_saved')
        self.assertEqual(payload['data']['entity_id'], 'abc')
        self.assertEqual(payload['data']['action'], 'open_saved')

    def test_listing_created_and_business_payloads(self):
        listing = listing_created_event(3, 'L1', 'Vehicles')
        self.assertEqual(listing['data']['type'], 'listing_created')
        self.assertEqual(listing['data']['entity_type'], 'listing')
        business = business_created_event(3, 'B1', 'shop')
        self.assertEqual(business['type'], 'business')
        self.assertEqual(business['data']['action'], 'open_dashboard')
        support = support_reply_event(3, 'T1')
        self.assertEqual(support['data']['type'], 'support_reply')
        self.assertEqual(support['data']['ticket_id'], 'T1')

    def test_chat_payload_keeps_model_type_chat(self):
        payload = chat_message_event(44, 'room-1', 12, 'm9')
        self.assertEqual(payload['type'], 'chat')
        self.assertEqual(payload['data']['type'], 'new_message')
        self.assertEqual(payload['data']['chat_id'], 'room-1')
        self.assertEqual(payload['data']['entity_id'], 'room-1')


class PreferenceHelperTests(TestCase):
    def test_event_maps_to_preference_keys(self):
        self.assertEqual(EVENT_TO_PREFERENCE['new_message'], 'messages')
        self.assertEqual(EVENT_TO_PREFERENCE['listing_created'], 'listing_activity')
        self.assertEqual(EVENT_TO_PREFERENCE['admin_announcement'], 'admin_announcements')

    @patch('notifications.services.preferences.NotificationPreference')
    def test_disabled_preference_blocks_delivery(self, mock_pref):
        mock_pref.for_user.return_value = SimpleNamespace(messages=False)
        self.assertFalse(is_preference_enabled(5, 'new_message'))

    @patch('notifications.services.preferences.NotificationPreference')
    def test_unknown_event_defaults_to_enabled(self, mock_pref):
        self.assertTrue(is_preference_enabled(5, 'unmapped_event'))
        mock_pref.for_user.assert_not_called()

    @patch('notifications.services.preferences.NotificationPreference')
    def test_upsert_only_accepts_known_bools(self, mock_pref):
        row = SimpleNamespace(
            messages=True,
            listing_activity=True,
            business_activity=True,
            marketing=True,
            system_security=True,
            admin_announcements=True,
            save=MagicMock(),
        )
        mock_pref.for_user.return_value = row
        result = upsert_preferences(1, {'messages': False, 'unknown': True})
        self.assertFalse(row.messages)
        self.assertFalse(result['messages'])
        row.save.assert_called_once()


class EmailTemplateTests(TestCase):
    def test_required_templates_exist(self):
        service = EmailTemplateService()
        for key in (
            'verify_email',
            'welcome',
            'password_reset',
            'password_changed',
            'security_alert',
            'listing_created',
            'business_activated',
            'support_reply',
        ):
            subject, html, text = service.render(key, {'otp': '123456', 'ttl_minutes': 15})
            self.assertTrue(subject)
            self.assertIn('Braelo', html)
            self.assertTrue(text)

    def test_unknown_template_raises(self):
        with self.assertRaises(ValueError):
            EmailTemplateService().get('not-a-template')


class NotificationAccessTests(TestCase):
    def test_owner_can_access_own_row(self):
        user = SimpleNamespace(id=12)
        note = SimpleNamespace(type='chat', user_id=[12])
        self.assertTrue(_user_can_access(note, user))
        self.assertFalse(_user_can_access(note, SimpleNamespace(id=99)))

    def test_admin_broadcast_visible_to_any_user(self):
        note = SimpleNamespace(type='admin', user_id=[1])
        self.assertTrue(_user_can_access(note, SimpleNamespace(id=99)))


class NotificationApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='notify@example.com',
            email='notify@example.com',
            name='Notify',
            password='pass12345',
            is_email_verified=True,
        )
        self.client = APIClient()
        token = str(RefreshToken.for_user(self.user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    @patch('notifications.api.preferences.preference_payload')
    def test_get_preferences(self, mock_payload):
        mock_payload.return_value = {
            'messages': True,
            'listing_activity': True,
            'business_activity': True,
            'marketing': False,
            'system_security': True,
            'admin_announcements': True,
        }
        response = self.client.get('/notifications/preferences')
        body = response.json()
        self.assertEqual(body.get('status'), 200)
        self.assertTrue(body['data']['messages'])
        self.assertFalse(body['data']['marketing'])

    @patch('notifications.api.preferences.upsert_preferences')
    def test_put_preferences(self, mock_upsert):
        mock_upsert.return_value = {
            'messages': False,
            'listing_activity': True,
            'business_activity': True,
            'marketing': True,
            'system_security': True,
            'admin_announcements': True,
        }
        response = self.client.put(
            '/notifications/preferences',
            data={'messages': False},
            format='json',
        )
        body = response.json()
        self.assertEqual(body.get('status'), 200)
        mock_upsert.assert_called_once()
        self.assertFalse(body['data']['messages'])

    def test_anonymous_cannot_read_preferences(self):
        anon = APIClient()
        response = anon.get('/notifications/preferences')
        self.assertIn(response.status_code, (401, 403))

    def test_event_send_is_staff_only(self):
        response = self.client.post(
            '/notifications/send',
            data={
                'type': 'chat',
                'title': 'x',
                'body': 'y',
                'user_id': [1],
                'data': {'type': 'new_message'},
            },
            format='json',
        )
        self.assertIn(response.status_code, (401, 403))
        self.assertNotEqual(response.json().get('status'), 201)

    def test_admin_notifications_url_alias(self):
        self.assertEqual(
            resolve('/admin-panel/notifications').func.view_class.__name__,
            'AllNotifications',
        )
        self.assertEqual(
            resolve('/admin-panel/notificatons').func.view_class.__name__,
            'AllNotifications',
        )


class DeviceTokenApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='device@example.com',
            email='device@example.com',
            name='Device',
            password='pass12345',
            is_email_verified=True,
        )
        self.client = APIClient()
        token = str(RefreshToken.for_user(self.user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    @patch('users.serializers.devices.UserDeviceToken')
    def test_register_token_uses_jwt_user(self, mock_device):
        mock_device.objects.return_value.first.return_value = None
        mock_device.objects.create.return_value = SimpleNamespace(
            platform='android',
            user_id=self.user.id,
        )
        response = self.client.post(
            '/auth/device/token',
            data={'token': 'fcm-abc', 'platform': 'android', 'email': 'spoof@x.com'},
            format='json',
        )
        body = response.json()
        self.assertEqual(body.get('status'), 201)
        kwargs = mock_device.objects.create.call_args.kwargs
        self.assertEqual(kwargs['user_id'], self.user.id)
        self.assertEqual(kwargs['email'], self.user.email)

    @patch('users.api.devices.UserDeviceToken')
    def test_delete_token_scoped_to_user(self, mock_device):
        query = MagicMock()
        mock_device.objects.return_value = query
        query.filter.return_value = query
        query.delete.return_value = 1
        response = self.client.delete(
            '/auth/device/token',
            data={'token': 'fcm-abc'},
            format='json',
        )
        body = response.json()
        self.assertEqual(body.get('status'), 200)
        mock_device.objects.assert_called_with(user_id=self.user.id)
