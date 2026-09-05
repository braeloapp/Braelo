"""
Email verification OTP lifecycle.

Tokens are stored hashed-equivalent as a short OTP with expiry and attempt
limits. Identity is always the user record, never a client-supplied user id.
"""

from __future__ import annotations

import logging

import pyotp
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from notifications.services.email import email_service
from users.models.users import EmailVerificationToken, User
from users.services.rate_limit import enforce_rate_limit

logger = logging.getLogger(__name__)

RESEND_LIMIT = 3
RESEND_WINDOW_SECONDS = 600
VERIFY_LIMIT = 8
VERIFY_WINDOW_SECONDS = 300


def _generate_otp() -> str:
    secret = pyotp.random_base32()
    return pyotp.TOTP(secret, digits=6, interval=300).now()


def send_verification_email(user: User, request=None) -> EmailVerificationToken:
    email_key = (user.email or '').strip().lower()
    enforce_rate_limit(request, 'email-verify-send', extra_key=email_key or None)

    EmailVerificationToken.objects.filter(
        user=user, used_at__isnull=True
    ).delete()
    otp = _generate_otp()
    record = EmailVerificationToken.objects.create(user=user, otp=otp)
    try:
        email_service.send(
            to=user.email,
            template_key='verify_email',
            context={
                'name': user.name or user.first_name or '',
                'otp': otp,
                'ttl_minutes': EmailVerificationToken.TTL_MINUTES,
            },
        )
    except Exception:
        logger.exception('Failed to send verification email to %s', user.email)
        raise ValidationError(
            {'email': 'Unable to send verification email. Please try again.'}
        )
    return record


def verify_email_otp(email: str, otp: str, request=None) -> User:
    email = (email or '').strip().lower()
    otp = (otp or '').strip()
    if request is not None:
        enforce_rate_limit(request, 'email-verify', extra_key=email or None)
    if not email or not otp:
        raise ValidationError({'otp': 'Email and verification code are required.'})

    user = User.objects.filter(email=email).first()
    if not user:
        raise ValidationError({'email': 'No account found for this email.'})
    if user.is_email_verified:
        return user

    record = (
        EmailVerificationToken.objects.filter(user=user, used_at__isnull=True)
        .order_by('-created_at')
        .first()
    )
    if record is None:
        raise ValidationError({'otp': 'No verification code found. Please resend.'})
    if record.has_expired():
        raise ValidationError({'otp': 'Verification code has expired.'})
    if record.attempts >= EmailVerificationToken.MAX_ATTEMPTS:
        raise ValidationError(
            {'otp': 'Too many incorrect attempts. Please resend a new code.'}
        )
    if record.otp != otp:
        record.attempts += 1
        record.save(update_fields=['attempts'])
        raise ValidationError({'otp': 'Invalid verification code.'})

    record.used_at = timezone.now()
    record.save(update_fields=['used_at'])
    user.is_email_verified = True
    user.save(update_fields=['is_email_verified'])
    email_service.send_best_effort(
        to=user.email,
        template_key='welcome',
        context={'name': user.name or user.first_name or ''},
    )
    return user
