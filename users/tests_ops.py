"""Phase 10 — health probes, rate limits, and upload validation."""

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from helpers.validate_upload import validate_image
from rest_framework.exceptions import ValidationError
from users.models import User
from users.services.rate_limit import (
    RATE_LIMIT_POLICIES,
    check_rate_limit,
    enforce_rate_limit,
    RateLimitExceeded,
    reset_rate_limits,
)


class HealthProbeTests(TestCase):
    def test_liveness_ok(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body.get("status"), "ok")
        self.assertEqual(body.get("service"), "braelo")

    def test_readiness_includes_sqlite(self):
        response = self.client.get("/readyz")
        self.assertIn(response.status_code, (200, 503))
        body = response.json()
        self.assertIn(body.get("status"), ("healthy", "degraded", "unavailable"))
        self.assertIn("sqlite", body.get("checks", {}))
        self.assertEqual(body["checks"]["sqlite"]["status"], "ok")


class RateLimitServiceTests(TestCase):
    def setUp(self):
        reset_rate_limits()

    def test_named_policies_cover_required_scopes(self):
        required = {
            "login",
            "admin-login",
            "signup",
            "social-login",
            "phone-login",
            "forgot-password",
            "password-otp",
            "email-verify-send",
            "feedback",
            "report",
            "chat-create",
            "search",
            "chatbot",
        }
        self.assertTrue(required.issubset(RATE_LIMIT_POLICIES))

    def test_enforce_raises_after_limit(self):
        class _Req:
            META = {"REMOTE_ADDR": "203.0.113.9"}

        request = _Req()
        for _ in range(8):
            enforce_rate_limit(request, "login", extra_key="burst@example.com")
        with self.assertRaises(RateLimitExceeded):
            enforce_rate_limit(request, "login", extra_key="burst@example.com")

    def test_memory_backend_still_blocks_burst(self):
        key = "ops-burst"
        for _ in range(3):
            self.assertTrue(check_rate_limit(key, limit=3, window_seconds=60))
        self.assertFalse(check_rate_limit(key, limit=3, window_seconds=60))


class LoginRateLimitApiTests(TestCase):
    def setUp(self):
        reset_rate_limits()
        self.user = User.objects.create_user(
            username="limited@example.com",
            email="limited@example.com",
            name="Limited",
            password="StrongPass123",
            is_email_verified=True,
        )

    def test_email_login_returns_429_after_burst(self):
        client = APIClient()
        last = None
        for _ in range(9):
            last = client.post(
                "/auth/login/email",
                data={"email": "limited@example.com", "password": "wrong-password"},
                format="json",
            )
        self.assertIsNotNone(last)
        self.assertEqual(last.status_code, 429)
        body = last.json()
        self.assertEqual(body.get("status"), 429)
        self.assertIn("Retry-After", last)


class AdminLoginRateLimitApiTests(TestCase):
    def setUp(self):
        reset_rate_limits()

    def test_admin_login_is_limited_separately(self):
        client = APIClient()
        last = None
        for _ in range(9):
            last = client.post(
                "/admin-panel/login",
                data={"email": "nobody@example.com", "password": "x"},
                format="json",
            )
        self.assertEqual(last.status_code, 429)
        self.assertEqual(last.json().get("status"), 429)


class ChatbotRateLimitTests(TestCase):
    def setUp(self):
        reset_rate_limits()

    def test_chatbot_returns_429_after_burst(self):
        class _Req:
            META = {"REMOTE_ADDR": "127.0.0.1"}

        request = _Req()
        for _ in range(20):
            enforce_rate_limit(request, "chatbot")
        response = self.client.post(
            "/chatbot/api/chat",
            data={"message": "hello"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 429)
        self.assertIn("Too many", response.json().get("error", ""))


class ImageValidationTests(TestCase):
    def test_rejects_non_image_extension(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        upload = SimpleUploadedFile(
            "payload.exe", b"MZ", content_type="application/octet-stream"
        )
        with self.assertRaises(ValidationError):
            validate_image(upload, "picture")

    def test_rejects_oversized_image(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        upload = SimpleUploadedFile(
            "big.jpg", b"not-a-real-jpeg", content_type="image/jpeg"
        )
        upload.size = 9 * 1024 * 1024
        with self.assertRaises(ValidationError):
            validate_image(upload, "picture")


@override_settings(DJANGO_SKIP_MONGOENGINE=True)
class JsonLogFormatterTests(TestCase):
    def test_json_formatter_emits_level(self):
        import json
        import logging

        from config.json_logging import JsonFormatter

        record = logging.LogRecord(
            name="braelo.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="ready",
            args=(),
            exc_info=None,
        )
        payload = json.loads(JsonFormatter().format(record))
        self.assertEqual(payload["level"], "INFO")
        self.assertEqual(payload["message"], "ready")
