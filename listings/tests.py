from unittest.mock import MagicMock, patch

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

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
