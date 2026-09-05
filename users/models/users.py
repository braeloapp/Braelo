'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
User model sql based.
---------------------------------------------------
'''

import random
from django.db import models
from datetime import timedelta
from django.utils import timezone
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.base_user import BaseUserManager


def get_random_profile_pic():
    '''
    assigns a user random pic upon signup
    '''
    PROFILE_PIC = [
        "https://braelos3.blob.core.windows.net/braelo/business_listings/Vehicles/8/profile-1.png",
        "https://braelos3.blob.core.windows.net/braelo/business_listings/Vehicles/8/profile-2.png",
        "https://braelos3.blob.core.windows.net/braelo/business_listings/Vehicles/8/profile-3.png",
        "https://braelos3.blob.core.windows.net/braelo/business_listings/Vehicles/8/profile-4.png",
    ]
    return random.choice(PROFILE_PIC)


class CustomUserManager(BaseUserManager):
    '''
    Custom user model manager where email is the unique identifiers
    for authentication instead of usernames.
    '''

    def create_user(self, username, **extra_fields):
        '''
        Create and save a User with the given email and password.
        '''
        if not username:
            raise ValueError('The Email must be set')
        uname = self.normalize_email(username)
        user = self.model(username=uname, **extra_fields)
        if extra_fields.get('password'):
            user.set_password(extra_fields['password'])
        user.save()
        return user

    def create_superuser(self, username, password, **extra_fields):
        '''
        Create and save a SuperUser with the given email and password.
        '''
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        extra_fields['password'] = password
        return self.create_user(username, **extra_fields)


class User(AbstractUser):

    USER_ROLES = (
        ('Admin', 'Admin'),
        ('Client', 'Client'),
    )

    email = models.EmailField(null=True, blank=True)
    password = models.CharField(max_length=255)
    profile_picture = models.CharField(
        max_length=255, default=get_random_profile_pic, blank=True
    )
    phone_number = models.CharField(max_length=15, null=True, blank=True)
    name = models.CharField(max_length=50, null=True, blank=True)
    first_name = models.CharField(max_length=50, null=True, blank=True)
    last_name = models.CharField(max_length=50, null=True, blank=True)
    google_id = models.CharField(max_length=255, null=True, blank=True)
    apple_id = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    is_email_verified = models.BooleanField(default=False)
    is_phone_verified = models.BooleanField(default=False)
    is_business = models.BooleanField(default=False)
    role = models.CharField(max_length=255, choices=USER_ROLES)

    # Recent Searches
    recent_searches = models.JSONField(blank=True, default=list)
    # Count for normal & business user(Dashoard)
    listings_count = models.IntegerField(default=0, blank=True)
    # Business dashboard
    listings_clicks = models.IntegerField(default=0, blank=True)
    business_interactions = models.IntegerField(default=0, blank=True)
    business_featured = models.IntegerField(default=0, blank=True)
    previous_business = models.BooleanField(default=False)
    # personal information
    dob = models.CharField(max_length=15, null=True, blank=True)
    gender = models.CharField(max_length=15, null=True, blank=True)
    # About app
    complement = models.CharField(max_length=15, null=True, blank=True)
    # Address information
    address = models.CharField(max_length=50, null=True, blank=True)
    country = models.CharField(max_length=20, null=True, blank=True)
    state = models.CharField(max_length=15, null=True, blank=True)
    city = models.CharField(max_length=15, null=True, blank=True)
    zip_code = models.CharField(max_length=15, null=True, blank=True)

    # Admin Panel
    is_warned = models.BooleanField(default=False)
    is_banned = models.BooleanField(default=False)

    # New field for storing OTP
    otp = models.CharField(max_length=6, null=True, blank=True)
    otp_created_at = models.DateTimeField(auto_now=True)
    username = models.CharField(
        max_length=255,
        verbose_name='username',
        unique=True,
        default='temp_username',
    )

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = []
    objects = CustomUserManager()

    def __str__(self):
        return f'{self.id}: {self.username}'


class OTP(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='otps'
    )
    otp = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    secret = models.CharField(max_length=32)
    expires_at = models.DateTimeField(blank=True)
    # Store the OTP secret for validation

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(minutes=10)
        super().save(*args, **kwargs)

    def has_expired(self):
        return timezone.now() > self.expires_at

    def __str__(self):
        return f"{self.user.email} - {self.otp}"


class EmailVerificationToken(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='email_verifications'
    )
    otp = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveIntegerField(default=0)
    used_at = models.DateTimeField(null=True, blank=True)

    MAX_ATTEMPTS = 5
    TTL_MINUTES = 15

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(
                minutes=self.TTL_MINUTES
            )
        super().save(*args, **kwargs)

    def has_expired(self):
        return timezone.now() > self.expires_at

    def is_usable(self):
        return self.used_at is None and not self.has_expired()

    def __str__(self):
        return f"{self.user.email} - email verify"
