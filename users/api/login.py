'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
User Login end-points module.
---------------------------------------------------
'''

from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from helpers import handle_exceptions, get_token, response
from users.permissions import is_admin_path
from users.serializers import EmailLogin, TokenBlacklistSerializer
from users.services.rate_limit import enforce_rate_limit

from users.models import Business

# login part


class LoginWithEmail(generics.CreateAPIView):
    serializer_class = EmailLogin
    permission_classes = [AllowAny]  # Ensure the user is authenticated

    @handle_exceptions
    def post(self, request, *args, **kwargs):
        '''
        POST method to handle user login on applications.
        :param request: request object. (dict)
        :return: user's signed up status. (json)
        '''
        data = request.data
        email = (data.get('email') or '').strip().lower()
        scope = 'admin-login' if is_admin_path(request) else 'login'
        enforce_rate_limit(request, scope, extra_key=email or None)
        user = self.get_serializer(data=data, context={'request': request})
        user.is_valid(raise_exception=True)
        user = user.validated_data
        token = get_token(user)
        business = Business.objects.filter(user_id=user.id).first()
        response_data = {
            'email': user.email,
            'name': user.name,
            'business_name': business.business_name if business else None,
            'token': token,
            'user_status': user.is_business,
            'is_warned': user.is_warned,
            'is_banned': user.is_banned,
            'is_email_verified': user.is_email_verified,
            'is_staff': user.is_staff,
            'is_superuser': user.is_superuser,
        }
        return response(
            status=status.HTTP_200_OK,
            message='user Logged in',
            data=response_data,
        )


class TokenRefresh(TokenRefreshView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        '''
        POST method to handle JWT token refreshing.
        :param request: request object containing refresh token.
        :return: new access token if refresh token is valid.
        '''
        enforce_rate_limit(request, 'token-refresh')
        refresh = super().post(request, *args, **kwargs)
        data = {
            'refresh': refresh.data.get('refresh', request.data['refresh']),
            'access': refresh.data['access'],
        }
        return response(
            status=status.HTTP_200_OK,
            message='Refreshed Token succesfully',
            data=data,
        )


class Logout(generics.CreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TokenBlacklistSerializer

    @handle_exceptions
    def post(self, request, **kwargs):
        '''
        POST method to handle user logout from applications.
        :param request: request object. (dict)
        :return: user's signed up status. (json)
        '''
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Extract the refresh token from request data
        refresh_token = request.data.get('refresh')
        token = RefreshToken(refresh_token)
        token.blacklist()
        device_token = (request.data.get('device_token') or '').strip()
        from users.models.devices import UserDeviceToken

        if device_token:
            UserDeviceToken.objects(
                user_id=request.user.id, token=device_token
            ).delete()
        return response(
            status=status.HTTP_200_OK,
            message='Logged out successfully.',
            data={'refresh_token': refresh_token},
            error='',
        )
