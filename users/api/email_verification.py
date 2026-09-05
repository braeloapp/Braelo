'''
Email verification endpoints.
'''

from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny

from helpers import get_token, handle_exceptions, response
from users.models import Business, User
from users.services.email_verification import (
    send_verification_email,
    verify_email_otp,
)


class VerifyEmail(generics.CreateAPIView):
    permission_classes = [AllowAny]

    @handle_exceptions
    def post(self, request, *args, **kwargs):
        email = (request.data.get('email') or '').strip().lower()
        otp = (request.data.get('otp') or '').strip()
        user = verify_email_otp(email, otp, request=request)
        token = get_token(user)
        try:
            business = Business.objects.filter(user_id=user.id).first()
            business_name = business.business_name if business else None
        except Exception:
            business_name = None
        return response(
            status=status.HTTP_200_OK,
            message='Email verified successfully.',
            data={
                'email': user.email,
                'name': user.name,
                'business_name': business_name,
                'token': token,
                'user_status': user.is_business,
                'is_email_verified': True,
            },
        )


class ResendEmailVerification(generics.CreateAPIView):
    permission_classes = [AllowAny]

    @handle_exceptions
    def post(self, request, *args, **kwargs):
        email = (request.data.get('email') or '').strip().lower()
        if not email:
            raise ValidationError({'email': 'Email is required.'})
        user = User.objects.filter(email=email).first()
        if user is None:
            return response(
                status=status.HTTP_200_OK,
                message='If an account exists, a verification email was sent.',
                data={},
            )
        if user.is_email_verified:
            return response(
                status=status.HTTP_200_OK,
                message='Email is already verified.',
                data={'is_email_verified': True},
            )
        send_verification_email(user, request=request)
        return response(
            status=status.HTTP_200_OK,
            message='Verification code sent to your email.',
            data={'email': user.email, 'is_email_verified': False},
        )
