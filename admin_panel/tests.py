from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from admin_panel.services.moderation import apply_user_moderation
from admin_panel.services.support import apply_support_filters, day_bounds
from listings.services.taxonomy import (
    build_taxonomy_catalog,
    humanize_key,
    validate_taxonomy_target,
)
from users.models import User
from users.serializers.signup import parse_signup_role


class SignupRoleParserTests(TestCase):
    def test_legacy_and_ui_values(self):
        self.assertEqual(parse_signup_role(True), 'admin')
        self.assertEqual(parse_signup_role('admin'), 'admin')
        self.assertEqual(parse_signup_role('subadmin'), 'admin')
        self.assertEqual(parse_signup_role('user'), 'user')
        self.assertEqual(parse_signup_role(False), 'user')


class ModerationRuleTests(TestCase):
    def test_first_warn_does_not_ban(self):
        user = SimpleNamespace(is_warned=False, is_banned=False, is_active=True)
        result = apply_user_moderation(user, 'warn')
        self.assertTrue(user.is_warned)
        self.assertFalse(result['banned'])
        self.assertFalse(user.is_banned)

    def test_second_warn_escalates_to_ban(self):
        user = SimpleNamespace(is_warned=True, is_banned=False, is_active=True)
        result = apply_user_moderation(user, 'warn')
        self.assertTrue(result['banned'])
        self.assertTrue(user.is_banned)
        self.assertFalse(user.is_active)

    def test_ignore_does_not_change_user(self):
        user = SimpleNamespace(is_warned=False, is_banned=False, is_active=True)
        result = apply_user_moderation(user, 'ignore')
        self.assertFalse(result['banned'])
        self.assertTrue(user.is_active)
        self.assertEqual(result['update_fields'], [])


class SupportFilterTests(TestCase):
    def test_day_bounds_parses_iso_date(self):
        start, end = day_bounds('2026-09-05')
        self.assertIsNotNone(start)
        self.assertEqual((end - start).days, 1)

    def test_apply_support_filters_forwards_email_and_status(self):
        queryset = MagicMock()
        queryset.filter.return_value = queryset
        apply_support_filters(
            queryset,
            {'search_email': 'a@b.com', 'request_status': 'Active'},
        )
        queryset.filter.assert_any_call(email__icontains='a@b.com')
        queryset.filter.assert_any_call(status='Active')


class TaxonomyCatalogTests(TestCase):
    def test_catalog_includes_code_owned_categories(self):
        catalog = build_taxonomy_catalog()
        keys = {row['key'] for row in catalog}
        self.assertIn('Vehicles', keys)
        self.assertIn('sportsandhobby', keys)
        vehicles = next(row for row in catalog if row['key'] == 'Vehicles')
        sub_keys = {row['key'] for row in vehicles['subcategories']}
        self.assertIn('Cars', sub_keys)

    def test_overrides_change_label_and_active(self):
        catalog = build_taxonomy_catalog(
            [
                SimpleNamespace(
                    key='Vehicles',
                    label='Autos',
                    is_active=False,
                    sort_order=0,
                    icon='',
                )
            ]
        )
        vehicles = next(row for row in catalog if row['key'] == 'Vehicles')
        self.assertEqual(vehicles['label'], 'Autos')
        self.assertFalse(vehicles['is_active'])

    def test_unknown_category_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_taxonomy_target('category', 'not-a-real-category')

    def test_humanize_known_keys(self):
        self.assertEqual(humanize_key('sportsandhobby'), 'Sports & Hobby')
        self.assertEqual(humanize_key('outdooractivities'), 'Outdoor Activities')


class AdminPanelApiTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            username='panel@example.com',
            email='panel@example.com',
            name='Panel',
            password='pass12345',
            is_staff=True,
            is_email_verified=True,
        )
        self.regular = User.objects.create_user(
            username='member@example.com',
            email='member@example.com',
            name='Member',
            password='pass12345',
            is_email_verified=True,
        )
        self.client = APIClient()
        token = str(RefreshToken.for_user(self.staff).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    def test_support_search_route_exists(self):
        with patch(
            'admin_panel.api.admin.AllFeedback.get_queryset',
            return_value=[],
        ), patch(
            'admin_panel.api.admin.AllFeedback.filter_queryset',
            return_value=[],
        ):
            response = self.client.get(
                '/admin-panel/support/search?search_email=a@b.com'
            )
        self.assertNotEqual(response.status_code, 404)

    def test_taxonomy_get_requires_staff(self):
        anon = APIClient()
        response = anon.get('/admin-panel/taxonomy')
        self.assertIn(response.status_code, (401, 403))

    @patch('admin_panel.api.taxonomy.TaxonomyOverride')
    def test_taxonomy_get_returns_catalog(self, mock_override):
        mock_override.objects.all.return_value = []
        response = self.client.get('/admin-panel/taxonomy')
        body = response.json()
        self.assertEqual(body.get('status'), 200)
        self.assertTrue(body['data']['categories'])
