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

from users.models import User
from django.utils import timezone
from rest_framework import serializers
from django.core.validators import validate_email
from rest_framework.serializers import ValidationError
from django.core.exceptions import ValidationError as DjangoValidationError


def _validate_email(email):
    '''
    Validates given email.
    :param email: email address. (string)
    :return: email address. (string)
    '''
    try:
        validate_email(email)
        return email
    except DjangoValidationError:
        raise ValidationError({'email': 'Enter a valid email address.'})


# todo Add role in all
class EmailSignup(serializers.Serializer):
    email = serializers.EmailField(required=True)
    name = serializers.CharField(required=True)
    password = serializers.CharField(write_only=True, required=True)
    role = serializers.BooleanField(required=False, default=False)

    class Meta:
        model = User
        fields = ['name', 'email', 'password', 'role']
        extra_kwargs = {'password': {'write_only': True}}

    def validate(self, data):
        admin_path = "/admin-panel/signup"
        request = self.context['request']
        email = data.get('email')
        password = data.get('password')
        if request.path == admin_path:
            role = request.data.get('role')
            if not role:
                raise ValidationError({'role': 'Admin must add role.'})
        if not email:
            raise ValidationError({'email': 'Email is required.'})
        if not password:
            raise ValidationError({'password': 'Password is required.'})
        email = _validate_email(email)
        if User.objects.filter(email=email).exists():
            raise ValidationError({'email': 'This email is already taken.'})
        # Password validation
        # data['password'] = make_password(password)
        return data

    def create(self, validated_data):
        if validated_data:
            validated_data['created_at'] = timezone.now()
            validated_data['updated_at'] = timezone.now()
            validated_data['is_staff'] = validated_data.get('role', False)
            validated_data['is_active'] = True
            validated_data['is_email_verified'] = True
            user = User.objects.create_user(**validated_data)
            return user
            # user = User(**validated_data)
            # if user.save():
            #     return user
        return None

    def update(self, instance, validated_data):
        instance.name = validated_data.get('name', instance.name)
        instance.email = validated_data.get('email', instance.email)
        instance.password = validated_data.get('password', instance.password)
        instance.save()
        return instance


# class PhoneSignup(serializers.Serializer):
#     phone_number = serializers.CharField(
#         min_length=11, max_length=15, required=True
#     )
#     otp = serializers.CharField(required=False, write_only=True)

#     # class Meta:
#     #     model = User
#     #     fields = ['phone_number']

#     def create(self, validated_data):
#         if validated_data:
#             validated_data['created_at'] = timezone.now()
#             validated_data['updated_at'] = timezone.now()
#             validated_data['is_active'] = True
#             validated_data['is_phone_verified'] = True
#             user = User.objects.create_user(**validated_data)
#             return user
#         return False

#     @staticmethod
#     def validate_phone_number(phone):
#         '''
#         Check if the phone number is valid.
#         '''
#         try:
#             # Parsing phone number
#             parsed_number = phonenumbers.parse(phone, None)
#             # Checking if the parsed number is a valid number
#             if not phonenumbers.is_valid_number(parsed_number):
#                 raise ValidationError('This is not valid phone number.')
#         except phonenumbers.NumberParseException:
#             raise ValidationError('This is not valid phone number.')
#         return phone

#     def send_otp(self, phone_number):
#         '''
#         Sends OTP via Twilio.
#         '''
#         client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
#         try:
#             verification = client.verify.v2.services(
#                 settings.TWILIO_VERIFY_SERVICE_SID
#             ).verifications.create(to=phone_number, channel='sms')
#             if verification.status != 'pending':
#                 raise ValidationError(
#                     {'otp': 'Failed to send OTP. Please try again later.'}
#                 )
#         except Exception as e:
#             raise ValidationError({'otp': f'Twilio Error: {str(e)}'})

#     def verify_otp(self, phone_number, otp):
#         '''
#         Verifies OTP via Twilio.
#         '''
#         client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
#         try:
#             verification_check = client.verify.v2.services(
#                 settings.TWILIO_VERIFY_SERVICE_SID
#             ).verification_checks.create(to=phone_number, code=otp)
#             if verification_check.status != 'approved':
#                 raise ValidationError({'otp': 'Invalid or expired OTP.'})
#         except Exception as e:
#             raise ValidationError({'otp': f'Twilio Error: {str(e)}'})

#     def validate(self, data):
#         phone_number = data.get('phone_number')
#         otp = data.get('otp')
#         if not phone_number:
#             raise ValidationError({'phone_number': 'phone number is required.'})
#         self.validate_phone_number(phone_number)

#         # Check if the phone_number exists
#         if User.objects.filter(phone_number=phone_number).exists():
#             raise ValidationError( {'Phone number': 'This Phone number is already taken.'})

#         # If OTP is provided, validate it
#         if otp:
#             self.verify_otp(phone_number, otp)
#         else:
#             # If no OTP is provided, send OTP
#             self.send_otp(phone_number)
#             raise serializers.ValidationError(
#                 {'otp': 'OTP sent to the provided phone number.'}
#             )
#         # Check if the email is valid
#         # user = User.objects.filter(phone_number=phone_number).first()
#         # if user:
#         #     raise ValidationError(
#         #         {'Phone number': 'This Phone number is already taken.'}
#         #     )
#         return data


# class GoogleSignup(serializers.Serializer):
#     '''
#     CRUD operation for User.
#     '''

#     email = serializers.EmailField(required=True)
#     name = serializers.CharField(max_length=50, required=True)
#     first_name = serializers.CharField(max_length=50, required=True)
#     last_name = serializers.CharField(max_length=50, required=True)
#     google_id = serializers.CharField(
#         min_length=11, max_length=255, required=True
#     )
#     created_at = serializers.DateTimeField(read_only=True)
#     updated_at = serializers.DateTimeField(read_only=True)
#     is_active = serializers.BooleanField(default=True)
#     is_email_verified = serializers.BooleanField(default=False)
#     is_phone_verified = serializers.BooleanField(default=False)

#     def validate(self, data):
#         '''
#         Check that the email or google id is not already taken.
#         '''
#         email = data.get('email')
#         google_id = data.get('google_id')
#         user = User.objects.filter(email=email).first()

#         if user:
#             if not user.google_id:
#                 user.google_id = google_id
#                 user.save()
#             token = get_token(user)
#             response_data = {'email': user.email, 'token': token}
#             return response(
#                 status=status.HTTP_200_OK,
#                 message='user logged in',
#                 data=response_data,
#             )
#         return data

#     def create(self, validated_data):
#         # if validated_data:
#         validated_data['created_at'] = timezone.now()
#         validated_data['updated_at'] = timezone.now()
#         validated_data['is_active'] = True
#         validated_data['username'] =  validated_data['email']
#         user = User.objects.create_user(**validated_data)
#         # user.username = validated_data['email']
#         # user.save()
#         return user
#             # return True
#         # return False

#     def update(self, google_user, **kwargs):
#         '''
#         Update the user details if any of the provided updated_user_data
#         differ from the existing data in the user object.
#         :param google_user: Dictionary containing updated user data from Google.(dict)
#         :return:
#         '''
#         user = User.objects.filter(email=google_user['email']).first()
#         is_updated = (
#             user.name != google_user['name']
#             or user.first_name != google_user['first_name']
#             or user.last_name != google_user['last_name']
#             or user.is_email_verified != google_user['is_email_verified']
#             or user.google_id != google_user['google_id']
#         )
#         if is_updated:
#             user.name = google_user['name']
#             user.first_name = google_user['first_name']
#             user.last_name = google_user['last_name']
#             user.is_email_verified = google_user['is_email_verified']
#             user.google_id = google_user['google_id']
#             user.updated_at = timezone.now()
#             user.save()
#         return user


# class AppleSignup(serializers.Serializer):
#     '''
#     CRUD operation for User.
#     '''

#     email = serializers.EmailField(required=True)
#     name = serializers.CharField(max_length=50, required=True)
#     first_name = serializers.CharField(max_length=50, required=True)
#     last_name = serializers.CharField(max_length=50, required=True)
#     google_id = serializers.CharField(
#         min_length=11, max_length=255, required=True
#     )
#     created_at = serializers.DateTimeField(read_only=True)
#     updated_at = serializers.DateTimeField(read_only=True)
#     is_active = serializers.BooleanField(default=True)
#     is_email_verified = serializers.BooleanField(default=False)
#     is_phone_verified = serializers.BooleanField(default=False)

#     def validate(self, data):
#         '''
#         Check that the email or phone number is not already taken.
#         '''
#         # directories
#         email = data['']
#         email = data.get('email')
#         google_id = data.get('google_id')
#         if email and User.objects.filter(email=email).first():
#             raise ValidationError({'email': 'This email is already taken.'})
#         if google_id and User.objects.filter(google_id=google_id).first():
#             raise ValidationError(
#                 {'google_id': 'This Google ID is already taken.'}
#             )
#         return data

#     def create(self, validated_data):
#         if validated_data:
#             validated_data['created_at'] = timezone.now()
#             validated_data['updated_at'] = timezone.now()
#             validated_data['is_active'] = True
#             user = User.objects.create_user(**validated_data)
#             return user
#             # return True
#         return False

#     def update(self, google_user, **kwargs):
#         '''
#         Update the user details if any of the provided updated_user_data
#         differ from the existing data in the user object.
#         :param google_user: Dictionary containing updated user data from Google.(dict)
#         :return:
#         '''
#         user = User.objects.filter(email=google_user['email']).first()
#         is_updated = (
#             user.name != google_user['name']
#             or user.first_name != google_user['first_name']
#             or user.last_name != google_user['last_name']
#             or user.is_email_verified != google_user['is_email_verified']
#             or user.google_id != google_user['google_id']
#         )
#         if is_updated:
#             user.name = google_user['name']
#             user.first_name = google_user['first_name']
#             user.last_name = google_user['last_name']
#             user.is_email_verified = google_user['is_email_verified']
#             user.google_id = google_user['google_id']
#             user.updated_at = timezone.now()
#             user.save()
#         return user
