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

import re
import unicodedata

from mongoengine import DoesNotExist
from rest_framework import serializers
from rest_framework.serializers import ValidationError

from helpers import INTERESTS
from users.models import Interest, User


def _interest_lookup_key(label):
    if not isinstance(label, str):
        return ''
    s = unicodedata.normalize('NFKC', label).replace('\u00a0', ' ')
    s = re.sub(r'&', ' and ', s, flags=re.IGNORECASE)
    s = s.casefold().strip()
    s = re.sub(r'[^a-z0-9]+', '', s)
    return s


_INTEREST_BY_LOOKUP_KEY = {}
for _canon in INTERESTS:
    _k = _interest_lookup_key(_canon)
    if _k and _k not in _INTEREST_BY_LOOKUP_KEY:
        _INTEREST_BY_LOOKUP_KEY[_k] = _canon

_INTERESTS_EXACT = frozenset(INTERESTS)


def _resolve_interest_tag(tag):
    if tag in _INTERESTS_EXACT:
        return tag
    k = _interest_lookup_key(tag)
    if k in _INTEREST_BY_LOOKUP_KEY:
        return _INTEREST_BY_LOOKUP_KEY[k]
    return None


class InterestSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(required=True)
    tags = serializers.JSONField(required=False, default=list)

    def validate_tags(self, tags):
        '''
        Check if the provided tags are correct.
        Resolves display labels (e.g. "Real estate") to INTERESTS canonical values (e.g. "realestate").
        '''
        if tags is None:
            return []
        if isinstance(tags, str):
            tags = [p for p in tags.split(',') if p and str(p).strip()]
        if isinstance(tags, dict):
            raise ValidationError('Incorrect tag.')
        if not isinstance(tags, (list, tuple)):
            raise ValidationError('Incorrect tag.')
        resolved = []
        seen = set()
        for tag in tags:
            if not isinstance(tag, str):
                raise ValidationError('Incorrect tag.')
            canon = _resolve_interest_tag(tag.strip())
            if canon is None:
                raise ValidationError('Incorrect tag.')
            if canon not in seen:
                seen.add(canon)
                resolved.append(canon)
        return resolved

    def validate_user_id(self, user_id):
        '''
        Check if the user_id already exists.
        :param user_id: id of user from mysql db. (int)
        :return: If it exists, return the existing object for update | user_id.
        '''
        try:
            # If user_id exists, return the corresponding Interest object (for updating)
            interest = Interest.objects.get(user_id=user_id)
            return interest
        except DoesNotExist:
            # If user_id does not exist, return the user_id (for creating a new entry)
            return user_id

    def create(self, validated_data):
        '''
        Create a new interest record for a user if it doesn't already exist.
        '''
        return Interest.objects.create(**validated_data)

    def update(self, instance, validated_data):
        '''
        Update the existing interest record for a user.
        '''
        instance.tags = validated_data.get('tags', instance.tags)
        instance.save()
        return instance

    def save(self, **kwargs):
        '''
        Save or update the user interest based on whether the user_id exists.
        '''
        interest = self.validated_data.get('user_id')
        if isinstance(interest, Interest):
            # If the validate_user_id returned an existing object, update it
            return self.update(interest, self.validated_data)
        else:
            # Otherwise, create a new interest
            return self.create(self.validated_data)


class UpdateProfileSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(required=False)
    name = serializers.CharField(required=False, allow_blank=True)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False, allow_blank=True)
    dob = serializers.CharField(required=False, allow_blank=True)
    gender = serializers.CharField(required=False, allow_blank=True)
    address = serializers.CharField(required=False, allow_blank=True)
    complement = serializers.CharField(required=False, allow_blank=True)
    country = serializers.CharField(required=False, allow_blank=True)
    state = serializers.CharField(required=False, allow_blank=True)
    city = serializers.CharField(required=False, allow_blank=True)
    zip_code = serializers.CharField(required=False, allow_blank=True)
    role = serializers.CharField(required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)
    is_email_verified = serializers.BooleanField(required=False)
    is_phone_verified = serializers.BooleanField(required=False)

    def validate(self, data):
        '''
        Validate profile updates. Staff on /admin-panel/user/update may edit
        email, phone, role, status, and verification flags for any user.
        '''
        request = self.context['request']
        admin_path = '/admin-panel/user/update'
        is_admin_update = request.path.startswith(admin_path)
        self.context['is_admin_update'] = is_admin_update

        if is_admin_update:
            from users.permissions import require_staff

            require_staff(request)
            user_id = data.get('user_id')
            if not user_id:
                raise ValidationError({'Field': 'Admin must provide user_id'})
            user = User.objects.filter(id=user_id).first()
            if not user:
                raise ValidationError({'error': 'user not found'})
            self.context['target_user'] = user
        else:
            user = request.user
            self.context['target_user'] = user

        email = data.get('email')
        phone = data.get('phone')

        if not is_admin_update and email and phone:
            raise ValidationError(
                'Only one of email or phone should be provided.'
            )

        if email not in (None, ''):
            if not is_admin_update and user.email:
                raise ValidationError(
                    {'email': 'Email is already set and cannot be changed.'}
                )
            clash = User.objects.filter(email=email).exclude(id=user.id)
            if clash.exists():
                raise ValidationError(
                    {'email': 'This email is already in use.'}
                )

        if phone not in (None, ''):
            if not is_admin_update and user.phone_number:
                raise ValidationError(
                    {
                        'phone': 'Phone number is already set and cannot be changed.'
                    }
                )
            clash = User.objects.filter(phone_number=phone).exclude(id=user.id)
            if clash.exists():
                raise ValidationError(
                    {'phone': 'This phone number is already in use.'}
                )

        if not is_admin_update:
            # Self-service: reject no-op updates
            same_checks = [
                ('name', 'name', user.name),
                ('first_name', 'first_name', user.first_name),
                ('last_name', 'last_name', user.last_name),
                ('dob', 'date_of_birth', user.dob),
                ('gender', 'gender', user.gender),
                ('address', 'address', user.address),
                ('complement', 'complement', user.complement),
                ('country', 'country', user.country),
                ('state', 'state', user.state),
                ('city', 'city', user.city),
                ('zip_code', 'zip_code', user.zip_code),
            ]
            for key, err_key, current in same_checks:
                value = data.get(key)
                if value not in (None, '') and value == current:
                    raise ValidationError({err_key: 'Already same.'})

        return data

    def save(self, **kwargs):
        '''
        Save or update the profile fields provided by user.
        '''
        user = self.context['target_user']
        validated_data = self.validated_data
        is_admin_update = self.context.get('is_admin_update', False)
        if not validated_data:
            return {}

        update_fields = []

        text_fields = [
            'name',
            'first_name',
            'last_name',
            'email',
            'dob',
            'gender',
            'address',
            'complement',
            'country',
            'state',
            'city',
            'zip_code',
        ]
        for field in text_fields:
            if field in validated_data:
                setattr(user, field, validated_data[field] or None)
                update_fields.append(field)

        if 'phone' in validated_data:
            user.phone_number = validated_data['phone'] or None
            update_fields.append('phone_number')

        if is_admin_update:
            if 'is_active' in validated_data:
                user.is_active = bool(validated_data['is_active'])
                update_fields.append('is_active')
            if 'is_email_verified' in validated_data:
                user.is_email_verified = bool(validated_data['is_email_verified'])
                update_fields.append('is_email_verified')
            if 'is_phone_verified' in validated_data:
                user.is_phone_verified = bool(validated_data['is_phone_verified'])
                update_fields.append('is_phone_verified')
            if 'role' in validated_data and validated_data['role'] not in (
                None,
                '',
            ):
                raw = str(validated_data['role']).strip().lower()
                if raw in ('admin', 'administrator'):
                    user.role = 'Admin'
                    user.is_staff = True
                else:
                    user.role = 'Client'
                    user.is_staff = False
                update_fields.extend(['role', 'is_staff'])

        if update_fields:
            user.save(update_fields=list(dict.fromkeys(update_fields)))
        return validated_data


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'email',
            'phone_number',
            'name',
            'first_name',
            'last_name',
            'google_id',
            'apple_id',
            'created_at',
            'updated_at',
            'is_active',
            'is_email_verified',
            'is_phone_verified',
            'role',
            'dob',
            'gender',
            'address',
            'complement',
            'country',
            'state',
            'city',
            'zip_code',
        ]
