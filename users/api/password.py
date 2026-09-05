'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
User password management end-points module.
---------------------------------------------------
'''

import pyotp
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated, AllowAny

from notifications.services.email import email_service

from users.models import OTP, User
from users.serializers import (
    ForgotPasswordSerializer,
    ChangePasswordSerializer,
    VerifyOtpSerializer,
    CreatePasswordSerializer,
)
from helpers import handle_exceptions, response


class ForgotPassword(generics.CreateAPIView):
    permission_classes = [AllowAny]  # Ensure the user is authenticated
    serializer_class = ForgotPasswordSerializer

    def _generate_otp(self):
        '''
        generates 6-digits otp code.
        :return: otp code. (int)
        '''
        # Generate the OTP
        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret, digits=6, interval=300)
        return totp.now()

    @handle_exceptions
    def post(self, request, *args, **kwargs):
        '''
        POST method to handle forgotten password.
        :param request: request object. (dict)
        :return: user's password status. (json)
        '''
        data = request.data
        user = self.get_serializer(data=data)
        user.is_valid(raise_exception=True)
        otp = self._generate_otp()
        email = user.validated_data['email']
        user = user.validated_data['user']
        OTP.objects.create(user=user, otp=otp)
        email_service.send(
            to=email,
            template_key='password_reset',
            context={
                'name': getattr(user, 'name', '') or '',
                'otp': otp,
                'ttl_minutes': 10,
            },
        )
        return response(
            status=status.HTTP_200_OK,
            message='OTP sent to your email.',
            data={},
        )


class VerifyOTP(generics.CreateAPIView):
    permission_classes = [AllowAny]
    queryset = User.objects.all()
    serializer_class = VerifyOtpSerializer

    @handle_exceptions
    def post(self, request, *args, **kwargs):
        '''
        POST method to handle user login in on applications.
        :param request: request object. (dict)
        :return: user's signed up status. (json)
        '''
        data = request.data
        user = self.get_serializer(data=data)
        user.is_valid(raise_exception=True)
        otp_rec = user.validated_data['otp_record']
        otp_rec.delete()
        return response(
            status=status.HTTP_200_OK,
            message='OTP verified successfully.',
            data={},
        )


class CreatePassword(generics.CreateAPIView):
    permission_classes = [AllowAny]
    serializer_class = CreatePasswordSerializer

    @handle_exceptions
    def post(self, request, *args, **kwargs):
        '''
        POST method to handle user change password on applications.
        :param request: request object. (dict)
        :return: user's password status. (json)
        '''
        data = request.data
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        resp = serializer.save()
        if not resp:
            # todo: needs better logic
            raise Exception('Cannot Add user to Database')
        return response(
            status=status.HTTP_201_CREATED,
            message='Password updated successfully',
            data=resp,
        )


class ChangePassword(generics.CreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ChangePasswordSerializer

    @handle_exceptions
    def post(self, request, *args, **kwargs):
        '''
        POST method to handle user change password on applications.
        :param request: request object. (dict)
        :return: user's password status. (json)
        '''
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        resp = serializer.save()
        if not resp:
            # todo: needs better logic
            raise Exception('Cannot Add user to Database')
        return response(
            status=status.HTTP_201_CREATED,
            message='Password updated successfully',
            data=resp,
        )
