'''
---------------------------------------------------
Project:        Braelo
Date:           March 20, 2025
Author:         Faizan
---------------------------------------------------

Description:
Serializer for admin_panel
---------------------------------------------------
'''

from rest_framework import serializers

from users.models import User


class UserSerializer(serializers.ModelSerializer):
    '''Admin user payload. Secrets and OTP material are never returned.'''

    class Meta:
        model = User
        fields = [
            'id',
            'email',
            'username',
            'name',
            'first_name',
            'last_name',
            'phone_number',
            'profile_picture',
            'is_active',
            'is_staff',
            'is_superuser',
            'is_email_verified',
            'is_phone_verified',
            'is_business',
            'is_warned',
            'is_banned',
            'role',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields
