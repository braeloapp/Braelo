'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
User sign up end-points module.
---------------------------------------------------
'''

import random
import phonenumbers
from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from users.permissions import DenyAdminPathUnlessStaff, is_admin_path, require_staff
from django.core.validators import validate_email
from rest_framework.exceptions import ValidationError
from django.views.decorators.csrf import csrf_exempt


from users.models import User
from users.models import Business

from users.serializers import EmailSignup
from users.services.firebase_identity import (
    email_from_firebase_claims,
    extract_id_token,
    name_parts_from_firebase_claims,
    phone_from_firebase_claims,
    uid_from_firebase_claims,
    verify_firebase_id_token,
)
from users.services.email_verification import send_verification_email
from users.services.rate_limit import check_rate_limit, client_ip
from helpers import (
    handle_exceptions,
    get_token,
    response,
)


class SignUpWithEmail(generics.CreateAPIView):

    queryset = User.objects.all()
    serializer_class = EmailSignup
    permission_classes = [AllowAny, DenyAdminPathUnlessStaff]

    @handle_exceptions
    def post(self, request, *args, **kwargs):
        '''
        POST method to handle user sign up on applications.
        :param request: request object. (dict)
        :return: user's signed up status. (json)
        '''
        data = request.data
        if is_admin_path(request):
            require_staff(request)
        user = self.get_serializer(data=data, context={'request': request})
        user.is_valid(raise_exception=True)
        # add username to the validated data
        user.validated_data['username'] = user.validated_data['email']
        user = user.create(user.validated_data)
        if not user:
            # todo: needs better logic
            raise Exception('Cannot Add user to Database')
        if is_admin_path(request):
            admin_data = {
                'email': user.email,
                'name': user.name,
                'created_at': user.created_at,
            }
            return response(
                status=status.HTTP_201_CREATED,
                message='User Signed Up',
                data=admin_data,
            )

        send_verification_email(user, request=request)
        data = {
            'email': user.email,
            'name': user.name,
            'user_status': user.is_business,
            'is_email_verified': False,
            'email_verification_required': True,
        }
        return response(
            status=status.HTTP_201_CREATED,
            message='Verification code sent to your email.',
            data=data,
        )


class LoginAuth(generics.CreateAPIView):

    permission_classes = [AllowAny]

    @staticmethod
    def validate_phone_number(phone):
        '''
        Check if the phone number is valid.
        '''
        try:
            # Parsing phone number
            parsed_number = phonenumbers.parse(phone, None)
            # Checking if the parsed number is a valid number
            if not phonenumbers.is_valid_number(parsed_number):
                raise ValidationError('This is not valid phone number.')
        except phonenumbers.NumberParseException:
            raise ValidationError('This is not valid phone number.')
        return phone

    def generate_username(self):
        '''
        Generates random name used in phone auth
        '''
        number = random.randint(
            1000, 9999999
        )  # Generate a random number with a wide range
        return f"User{number}"

    @staticmethod
    def _phone_candidates(phone_number):
        raw = (phone_number or "").strip()
        digits = "".join(ch for ch in raw if ch.isdigit())
        candidates = {raw, digits}
        if raw.startswith("+"):
            candidates.add(raw[1:])
        if digits:
            candidates.add(f"+{digits}")
        return [item for item in candidates if item]

    def _find_user_by_phone(self, phone_number):
        candidates = self._phone_candidates(phone_number)
        if not candidates:
            return None
        return User.objects.filter(phone_number__in=candidates).first()

    @staticmethod
    def _business_name_for_user(user):
        try:
            business = Business.objects.filter(user_id=user.id).first()
        except Exception:
            return None
        return business.business_name if business else None

    def authenticate_user(self, login_type, data):
        '''
        Google/Apple login. Identity comes only from a verified Firebase ID token.
        Client-supplied email, name, and provider IDs are ignored.
        '''
        claims = verify_firebase_id_token(extract_id_token(data))
        email = email_from_firebase_claims(claims)
        provider_id = uid_from_firebase_claims(claims)
        validate_email(email)
        token_name, token_first, token_last = name_parts_from_firebase_claims(
            claims
        )
        email_verified = bool(claims.get('email_verified'))
        display_name = token_name or email.split('@')[0]
        first_name = token_first or display_name
        last_name = token_last or display_name

        user_data = {
            'email': email,
            f'{login_type}_id': provider_id,
            'username': email,
            'name': display_name,
            'first_name': first_name,
            'last_name': last_name,
            'is_email_verified': email_verified,
        }

        user = User.objects.filter(email=email).first()
        if user is None:
            user = User.objects.filter(
                **{f'{login_type}_id': provider_id}
            ).first()

        if user:
            if user.is_banned:
                raise ValidationError(
                    {'User': 'Sorry, Your Account is Banned.'}
                )
            update_fields = []
            existing_provider_id = getattr(user, f'{login_type}_id', None)
            if existing_provider_id is None:
                setattr(user, f'{login_type}_id', provider_id)
                update_fields.append(f'{login_type}_id')
            if email_verified and not user.is_email_verified:
                user.is_email_verified = True
                update_fields.append('is_email_verified')
            if update_fields:
                user.save(update_fields=update_fields)

            token = get_token(user)
            return {
                'email': user.email,
                'name': user.name,
                'business_name': self._business_name_for_user(user),
                'token': token,
                'user_status': user.is_business,
                'is_warned': user.is_warned,
                'is_banned': user.is_banned,
            }

        provider_id_check = User.objects.filter(
            **{f'{login_type}_id': provider_id}
        ).exists()
        if provider_id_check:
            raise ValidationError(
                {f'{login_type}_id': 'Already exists for another user'}
            )

        new_user = User.objects.create(**user_data)
        new_token = get_token(new_user)
        return {
            'email': new_user.email,
            'name': new_user.name,
            'token': new_token,
            'user_status': new_user.is_business,
        }

    @handle_exceptions
    @csrf_exempt
    def post(self, request):
        '''
        POST method to handle user signup/login on applications.
        :param request: request object. (dict)
        :return: user's signed up status. (json)
        '''

        login_type = request.GET.get('login_type')
        if login_type not in ('google', 'apple', 'phone'):
            raise ValidationError(
                {'Type': 'Must be ["google","apple","phone"]'}
            )
        if login_type in ['google', 'apple']:
            ip = client_ip(request)
            if not check_rate_limit(
                f"social-login:{ip}", limit=8, window_seconds=300
            ):
                raise ValidationError(
                    {
                        'detail': (
                            'Too many login attempts. Please try again later.'
                        )
                    }
                )
            data = self.authenticate_user(login_type, request.data)
            return response(
                status=status.HTTP_200_OK,
                message='user logged in',
                data=data,
            )

        # Phone login: JWT is issued only after a verified Firebase ID token.
        # Client-supplied phone_number is ignored for identity.
        if login_type == 'phone':
            ip = client_ip(request)
            if not check_rate_limit(f"phone-login:{ip}", limit=8, window_seconds=300):
                raise ValidationError(
                    {
                        'detail': (
                            'Too many phone login attempts. Please try again later.'
                        )
                    }
                )
            claims = verify_firebase_id_token(extract_id_token(request.data))
            phone_number = phone_from_firebase_claims(claims)
            self.validate_phone_number(phone_number)
            user = self._find_user_by_phone(phone_number)
            if user:
                if user.is_banned:
                    raise ValidationError(
                        {'User': 'Sorry, Your Account is Banned.'}
                    )
                update_fields = []
                if user.phone_number != phone_number:
                    user.phone_number = phone_number
                    update_fields.append('phone_number')
                if not user.is_phone_verified:
                    user.is_phone_verified = True
                    update_fields.append('is_phone_verified')
                if update_fields:
                    user.save(update_fields=update_fields)
                token = get_token(user)
                data = {
                    'phone': user.phone_number,
                    'name': user.name,
                    'business_name': self._business_name_for_user(user),
                    'token': token,
                    'user_status': user.is_business,
                    'is_warned': user.is_warned,
                    'is_banned': user.is_banned,
                }
                return response(
                    status=status.HTTP_200_OK,
                    message='User logged in',
                    data=data,
                )
            username = self.generate_username()
            new_user = User.objects.create(
                username=username,
                name=username,
                first_name=username,
                last_name=username,
                phone_number=phone_number,
                is_phone_verified=True,
            )
            token = get_token(new_user)
            data = {
                'phone': new_user.phone_number,
                'name': new_user.name,
                'token': token,
                'user_status': new_user.is_business,
            }
            return response(
                status=status.HTTP_200_OK,
                message='User logged in',
                data=data,
            )
