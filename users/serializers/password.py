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

from django.db import transaction
from rest_framework import serializers
from rest_framework.serializers import ValidationError
from django.contrib.auth.password_validation import validate_password

from notifications.services.email import email_service
from users.models import User, OTP


class ChangePasswordSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    old_password = serializers.CharField(required=True, write_only=True)
    new_password = serializers.CharField(required=True, write_only=True)
    confirm_password = serializers.CharField(required=True, write_only=True)

    def validate(self, data):
        '''
        Check that the old password still exists.
        '''
        current_password = data.get('old_password')
        new_password = data.get('new_password')
        confirm_password = data.get('confirm_password')
        user = User.objects.filter(email=data['email']).first()
        if not user:
            raise ValidationError(
                {'email': 'No user found with this email address.'}
            )
        if not user.check_password(current_password):
            raise ValidationError({'old_password': ['Incorrect password.']})
        if current_password == new_password:
            raise ValidationError(
                {
                    'new_password': 'New password cannot be the same as the old password.'
                }
            )
        if new_password != confirm_password:
            raise ValidationError(
                {
                    'new_password': 'The new password and confirmation password do not match.'
                }
            )
        # todo: Apply this check
        #  validate_password(new_password, user=user)
        return data

    def save(self, **kwargs):
        email = self.validated_data.get('email')
        new_password = self.validated_data.get('new_password')
        with transaction.atomic():
            # Fetch the user and set the new password
            user = User.objects.get(email=email)
            user.set_password(new_password)
            user.save()
        email_service.send_best_effort(
            to=user.email,
            template_key='password_changed',
            context={'name': user.name or user.first_name or ''},
        )
        return {'email': user.email}


class CreatePasswordSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    new_password = serializers.CharField(required=True, write_only=True)
    confirm_password = serializers.CharField(required=True, write_only=True)

    def validate(self, data):
        '''
        Check that the old password still exists.
        '''
        email = data.get('email')
        new_password = data.get('new_password')
        confirm_password = data.get('confirm_password')
        user = User.objects.filter(email=email).first()
        if not user:
            raise ValidationError(
                {'email': 'No user found with this email address.'}
            )
        if user.check_password(new_password):
            raise ValidationError(
                {
                    'new_password': 'The new password cannot be the same as the current password.'
                }
            )
        if new_password != confirm_password:
            raise ValidationError(
                {
                    'new_password': 'The new password and confirmation password do not match.'
                }
            )
        # todo: Apply this check
        #  validate_password(new_password, user=user)
        return data

    def save(self, **kwargs):
        email = self.validated_data.get('email')
        new_password = self.validated_data.get('new_password')
        with transaction.atomic():
            # Fetch the user and set the new password
            user = User.objects.get(email=email)
            user.set_password(new_password)
            user.save()
        email_service.send_best_effort(
            to=user.email,
            template_key='password_changed',
            context={'name': user.name or user.first_name or ''},
        )
        return {'email': user.email}


class VerifyOtpSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    otp = serializers.CharField(required=True, max_length=6)

    def validate(self, data):
        otp = data.get('otp')
        email = data.get('email')
        try:
            otp_record = OTP.objects.get(user__email=email, otp=otp)
        except OTP.DoesNotExist:
            raise ValidationError('Invalid OTP or email.')
        if otp_record.has_expired():
            raise ValidationError('This OTP has expired.')
        data['otp_record'] = otp_record
        return data


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)

    def validate(self, data):
        '''
        Validate that the email exists in the database.
        '''
        email = data.get('email')
        user = User.objects.filter(email=email).first()
        if not user:
            raise ValidationError('No user found with this email address.')
        data['user'] = user
        return data
