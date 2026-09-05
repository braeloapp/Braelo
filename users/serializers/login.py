'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------
Description:
Serializer file for users based endpoints
---------------------------------------------------
'''

from datetime import timedelta
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.serializers import ValidationError
from django.contrib.auth.hashers import check_password
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

from users.models import User


class PhoneLogin(serializers.Serializer):
    phone_number = serializers.CharField(
        min_length=11, max_length=15, required=True
    )
    otp = serializers.CharField(min_length=6, max_length=6, required=True)

    class Meta:
        model = User
        fields = ['phone_number']

    def validate(self, data):
        otp = data.get('otp')
        phone_number = data.get('phone_number')
        # Check if the user with the provided email exists
        user = User.objects.filter(phone_number=phone_number).first()
        if not user:
            raise ValidationError(
                {'Phone number': 'No user found with this Phone Number.'}
            )
        if not self.is_otp_valid(phone_number, otp):
            raise ValidationError({'otp': 'The OTP is invalid or has expired.'})
        return user

    def is_otp_valid(self, phone, otp):
        '''
        Validates otp and phone number.
        :param phone: phone number. (string)
        :param otp: otp code. (int)
        :return: True if validates, otherwise false.(boolean)
        '''
        user = User.objects.filter(phone_number=phone, otp=otp).first()
        if not user:
            return False
        # Temporary adding day 1 limit for testing
        expiry_time = user.otp_created_at + timedelta(days=1)
        return timezone.now() < expiry_time


class EmailLogin(serializers.Serializer):
    class Meta:
        model = User
        fields = ['email', 'password']
        extra_kwargs = {'password': {'write_only': True}}

    email = serializers.EmailField(required=True)
    password = serializers.CharField(required=True)

    def validate(self, data):
        request = self.context['request']
        admin_path = "/admin-panel/login"
        email = data.get('email')
        password = data.get('password')
        # Check if the user with the provided email exists
        user = User.objects.filter(email=email).first()
        if not user:
            raise ValidationError(
                {'email': 'No user found with this email address.'}
            )
        if user.is_banned:
            raise ValidationError({'User': 'Sorry, Your Account is Banned.'})
        if request.path == admin_path and not (
            user.is_staff or user.is_superuser
        ):
            raise ValidationError({'error': 'Access denied. Admins only.'})
        # Check if the provided password matches the stored password
        if not check_password(password, user.password):
            raise ValidationError({'password': 'Incorrect password.'})
        if request.path != admin_path and not user.is_email_verified:
            raise ValidationError(
                {
                    'email_unverified': True,
                    'email': (
                        'Please verify your email before signing in.'
                    ),
                }
            )

        # If the user is inactive, reactivate the account
        if not user.is_active:
            user.is_active = True
            user.save(update_fields=['is_active'])
        return user


# LOGOUT


class TokenBlacklistSerializer(serializers.Serializer):
    refresh = serializers.CharField(required=True)

    def validate_refresh(self, value):
        '''
        Check if the refresh token has already been blacklisted.
        '''
        try:
            # Try to retrieve the refresh token
            token = RefreshToken(value)
            # Check if the token is already blacklisted
            if BlacklistedToken.objects.filter(
                token__jti=token['jti']
            ).exists():
                raise ValidationError(
                    'This token has already been blacklisted.'
                )
        except Exception as exc:
            raise ValidationError(str(exc))
        return value
