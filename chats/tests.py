from datetime import datetime, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from chats.api.chat import ChatroomListApi
from chats.services import (
    is_participant,
    normalize_user_id,
    parse_before_cursor,
    peer_user_id,
)
from users.models import User


class ChatHelperTests(TestCase):
    def test_peer_user_id_ignores_caller(self):
        chat = SimpleNamespace(participants=['12', '34'])
        self.assertEqual(peer_user_id(chat, 12), '34')
        self.assertEqual(peer_user_id(chat, '34'), '12')

    def test_is_participant_string_and_int(self):
        chat = SimpleNamespace(participants=['12', '34'])
        self.assertTrue(is_participant(chat, 12))
        self.assertFalse(is_participant(chat, 99))

    def test_normalize_user_id(self):
        self.assertEqual(normalize_user_id(12), '12')
        self.assertEqual(normalize_user_id(None), '')

    def test_parse_before_cursor_iso(self):
        parsed = parse_before_cursor('2026-09-05T10:00:00Z')
        self.assertIsInstance(parsed, datetime)
        self.assertTrue(timezone.is_aware(parsed))

    def test_parse_before_cursor_rejects_garbage(self):
        with self.assertRaises(ValidationError):
            parse_before_cursor('yesterday')

    def test_parse_before_cursor_blank(self):
        self.assertIsNone(parse_before_cursor(''))
        self.assertIsNone(parse_before_cursor(None))


class ChatroomListApiTests(TestCase):
    def test_paginate_is_read_only(self):
        self.assertNotIn(
            'post', [m.lower() for m in ChatroomListApi.http_method_names]
        )


class ChatroomDetailAuthorizationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='chat-owner@example.com',
            email='chat-owner@example.com',
            name='Owner',
            password='pass12345',
            is_email_verified=True,
        )
        self.client = APIClient()
        token = str(RefreshToken.for_user(self.user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    @patch('chats.api.chat.Chat')
    def test_detail_forbids_non_participant(self, mock_chat):
        room = SimpleNamespace(participants=['999', '1000'], chat_id='abc')
        mock_chat.objects.filter.return_value.first.return_value = room
        response = self.client.get('/chats/detail/abc')
        body = response.json()
        self.assertEqual(body.get('status'), 403)

    @patch('chats.api.chat.Chat')
    def test_detail_missing_room_is_forbidden(self, mock_chat):
        mock_chat.objects.filter.return_value.first.return_value = None
        response = self.client.get('/chats/detail/missing')
        self.assertEqual(response.json().get('status'), 403)


class CreateChatBlockTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='blocker@example.com',
            email='blocker@example.com',
            name='Blocker',
            password='pass12345',
            is_email_verified=True,
        )
        self.other = User.objects.create_user(
            username='blocked@example.com',
            email='blocked@example.com',
            name='Blocked',
            password='pass12345',
            is_email_verified=True,
        )
        self.client = APIClient()
        token = str(RefreshToken.for_user(self.user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    @patch('chats.api.chat.assert_not_blocked', side_effect=PermissionDenied('blocked'))
    def test_create_chat_rejects_blocked_pair(self, _mock_block):
        response = self.client.post(
            '/chats/create',
            data={'user_id': self.other.id, 'sender': 'false', 'receiver': 'false'},
            format='json',
        )
        self.assertEqual(response.json().get('status'), 400)


class ReportUserValidationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='reporter@example.com',
            email='reporter@example.com',
            name='Reporter',
            password='pass12345',
            is_email_verified=True,
        )
        self.other = User.objects.create_user(
            username='target@example.com',
            email='target@example.com',
            name='Target',
            password='pass12345',
            is_email_verified=True,
        )
        self.client = APIClient()
        token = str(RefreshToken.for_user(self.user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    def test_cannot_report_self(self):
        response = self.client.post(
            '/report/user',
            data={'reported_to': self.user.id, 'report_checkbox': 'Scam'},
            format='json',
        )
        self.assertEqual(response.json().get('status'), 400)

    def test_unknown_user_is_rejected(self):
        response = self.client.post(
            '/report/user',
            data={'reported_to': 999999, 'report_checkbox': 'Scam'},
            format='json',
        )
        self.assertEqual(response.json().get('status'), 400)

    def test_valid_report_payload_passes_serializer(self):
        from feedbacks.serializers.report_user import ReportMessageSerializer

        request = SimpleNamespace(user=self.user)
        serializer = ReportMessageSerializer(
            data={
                'reported_to': self.other.id,
                'report_checkbox': 'Scam',
                'issue_description': 'Suspicious listing',
            },
            context={'request': request},
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)


class MessageCursorTests(TestCase):
    def test_aware_datetime_passthrough(self):
        value = datetime(2026, 9, 5, 12, 0, tzinfo=dt_timezone.utc)
        self.assertEqual(parse_before_cursor(value), value)
