from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase
from rest_framework.exceptions import ValidationError

from config.environment import (
    INSECURE_SECRET_KEY,
    resolve_cors_allow_all,
    resolve_debug,
    resolve_django_env,
    resolve_public_backend_url,
    resolve_secret_key,
)
from users.models import User
from users.services.firebase_identity import (
    extract_id_token,
    phone_from_firebase_claims,
    verify_firebase_id_token,
)
from users.services.rate_limit import check_rate_limit, reset_rate_limits


class EnvironmentResolutionTests(TestCase):
    def test_azure_implies_production(self):
        self.assertEqual(
            resolve_django_env({"WEBSITE_SITE_NAME": "Braelo-V1"}),
            "production",
        )

    def test_explicit_env_wins(self):
        self.assertEqual(
            resolve_django_env(
                {"DJANGO_ENV": "staging", "WEBSITE_SITE_NAME": "Braelo-V1"}
            ),
            "staging",
        )

    def test_local_defaults_to_development(self):
        self.assertEqual(resolve_django_env({}), "development")

    def test_debug_defaults_false_in_production(self):
        self.assertFalse(resolve_debug({}, "production"))
        self.assertTrue(resolve_debug({}, "development"))

    def test_explicit_debug_wins(self):
        self.assertTrue(resolve_debug({"DEBUG": "true"}, "production"))
        self.assertFalse(resolve_debug({"DEBUG": "0"}, "development"))

    def test_secret_key_required_in_production(self):
        with self.assertRaises(ImproperlyConfigured):
            resolve_secret_key({}, "production", False)

    def test_insecure_secret_rejected_when_not_debug(self):
        with self.assertRaises(ImproperlyConfigured):
            resolve_secret_key(
                {"SECRET_KEY": INSECURE_SECRET_KEY},
                "development",
                False,
            )

    def test_dev_secret_fallback_only_when_debug(self):
        self.assertEqual(
            resolve_secret_key({}, "development", True),
            INSECURE_SECRET_KEY,
        )

    def test_cors_closed_when_not_debug(self):
        self.assertFalse(resolve_cors_allow_all({}, False))
        self.assertTrue(resolve_cors_allow_all({}, True))

    def test_public_backend_url_no_lan_default(self):
        prod = resolve_public_backend_url({}, "production")
        dev = resolve_public_backend_url({}, "development")
        self.assertTrue(prod.startswith("https://"))
        self.assertNotIn("192.168.", prod)
        self.assertNotIn("192.168.", dev)
        self.assertEqual(
            resolve_public_backend_url(
                {"PUBLIC_BACKEND_URL": "https://api.example.com/"},
                "production",
            ),
            "https://api.example.com",
        )


class DebugEndpointTests(TestCase):
    def test_test_env_removed(self):
        response = self.client.get("/test-env/")
        self.assertEqual(response.status_code, 404)

    def test_debug_knowledge_anonymous_404(self):
        response = self.client.get("/chatbot/api/debug/knowledge")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("openai_key_set", response.content.decode())

    def test_learning_gaps_anonymous_404(self):
        response = self.client.get("/chatbot/api/learning-gaps")
        self.assertEqual(response.status_code, 404)


class FirebaseIdentityTests(TestCase):
    def test_missing_token_rejected(self):
        with self.assertRaises(ValidationError):
            verify_firebase_id_token("")

    def test_extract_id_token_prefers_canonical_key(self):
        self.assertEqual(
            extract_id_token({"id_token": "abc", "firebase_token": "xyz"}),
            "abc",
        )

    def test_phone_required_on_claims(self):
        with self.assertRaises(ValidationError):
            phone_from_firebase_claims({"uid": "x"})

    def test_expired_token_message(self):
        import sys
        import types

        class ExpiredIdTokenError(Exception):
            pass

        fake_auth = types.ModuleType("firebase_admin.auth")

        def _verify(_token):
            raise ExpiredIdTokenError("expired")

        fake_auth.verify_id_token = _verify
        fake_admin = types.ModuleType("firebase_admin")
        fake_admin.auth = fake_auth

        with patch.dict(
            sys.modules,
            {"firebase_admin": fake_admin, "firebase_admin.auth": fake_auth},
        ):
            with self.assertRaises(ValidationError) as ctx:
                verify_firebase_id_token("expired-token")
        self.assertIn("expired", str(ctx.exception.detail).lower())


class PhoneLoginFirebaseTests(TestCase):
    def setUp(self):
        reset_rate_limits()

    def test_phone_login_without_token_rejected(self):
        response = self.client.post(
            "/auth/login?login_type=phone",
            data={"phone_number": "+14155552671"},
            content_type="application/json",
        )
        body = response.json()
        self.assertEqual(body.get("status"), 400)
        self.assertIsNone((body.get("data") or {}).get("token"))

    def test_client_phone_cannot_issue_jwt(self):
        response = self.client.post(
            "/auth/login?login_type=phone",
            data={"phone_number": "+19995550123", "id_token": ""},
            content_type="application/json",
        )
        body = response.json()
        self.assertEqual(body.get("status"), 400)
        self.assertFalse(User.objects.filter(phone_number="+19995550123").exists())

    @patch("users.api.signup.verify_firebase_id_token")
    def test_verified_token_issues_jwt_using_token_phone(self, mock_verify):
        mock_verify.return_value = {
            "uid": "firebase-uid-1",
            "phone_number": "+14155552671",
        }
        response = self.client.post(
            "/auth/login?login_type=phone",
            data={
                "phone_number": "+19990001111",
                "id_token": "valid-firebase-token",
            },
            content_type="application/json",
        )
        body = response.json()
        self.assertEqual(body.get("status"), 200)
        self.assertEqual(body["data"]["phone"], "+14155552671")
        self.assertIn("access", body["data"]["token"])
        user = User.objects.get(phone_number="+14155552671")
        self.assertTrue(user.is_phone_verified)
        self.assertFalse(User.objects.filter(phone_number="+19990001111").exists())

    @patch("users.api.signup.verify_firebase_id_token")
    def test_existing_user_is_reused(self, mock_verify):
        user = User.objects.create(
            username="existing-phone",
            name="Existing",
            phone_number="+14155552671",
            is_phone_verified=False,
        )
        mock_verify.return_value = {
            "uid": "firebase-uid-2",
            "phone_number": "+14155552671",
        }
        response = self.client.post(
            "/auth/login?login_type=phone",
            data={"id_token": "valid-firebase-token"},
            content_type="application/json",
        )
        body = response.json()
        self.assertEqual(body.get("status"), 200)
        user.refresh_from_db()
        self.assertTrue(user.is_phone_verified)
        self.assertEqual(User.objects.filter(phone_number="+14155552671").count(), 1)

    def test_rate_limit_blocks_burst(self):
        key = "phone-login:test-burst"
        for _ in range(8):
            self.assertTrue(check_rate_limit(key, limit=8, window_seconds=300))
        self.assertFalse(check_rate_limit(key, limit=8, window_seconds=300))
