'''
---------------------------------------------------
Project:        Braelo
Date:           Dec 20, 2024
Author:         Faizan
---------------------------------------------------

Description:
Fetch Business Serializers.
---------------------------------------------------
'''

from django.db import transaction
from django.utils import timezone
from rest_framework_mongoengine import serializers
from rest_framework.exceptions import ValidationError
from rest_framework import serializers as SQL_serializer

from users.models import User, Business
from config import AZURE_CONTAINER_NAME
from helpers.azure import blob_service_client
from helpers import (
    CATEGORIES,
    upload_pictures,
    validate_image,
    validate_phone,
    email_validation,
)
from admin_panel.models import AdminBusinessBanner
from admin_panel.serializers import BusinessBannerSerializer


class BusinessSerailizer(serializers.DocumentSerializer):
    '''
    Serailizer for business listings
    '''

    class Meta:
        model = Business
        fields = '__all__'

    def check_duplicate(self, field, value, exclude_id=None, error_msg=None):
        queryset = Business.objects.filter(**{field: value})
        if exclude_id:
            queryset = queryset.exclude(id=exclude_id)
        if queryset.first():
            raise ValidationError({'error': error_msg})

    def update_media(
        self, instance_images, business_type, new_images, user_id, image_type
    ):

        # Delete already existed ones
        for picture_url in instance_images:
            # Extract the blob name from the URL
            blob_name = picture_url.split(f'/{AZURE_CONTAINER_NAME}/')[-1]
            blob_client = blob_service_client.get_blob_client(
                container=AZURE_CONTAINER_NAME, blob=blob_name
            )
            blob_client.delete_blob()
            # Upload New ones
        s3_urls = upload_pictures(
            new_images,
            business_type,
            user_id,
            image_type,
        )
        return s3_urls

    def create(self, validated_data):
        '''
        handles the creation of business after validating pictures
        '''
        user = self.context['request'].user
        business_category = validated_data.get('business_category')
        bussines_logo = validated_data.get('business_logo', [])
        business_images = validated_data.get('business_images', [])
        business_banner = validated_data.get('business_banner', [])

        # Upload Logo
        s3_logo_url = upload_pictures(
            bussines_logo,
            business_category,
            user.id,
            image_type='business_logo',
        )
        # Upload Business Images
        s3_image_urls = upload_pictures(
            business_images,
            business_category,
            user.id,
            image_type='business_images',
        )
        # Upload banner
        s3_banner_urls = upload_pictures(
            business_banner,
            business_category,
            user.id,
            image_type='business_banner',
        )
        # Add Urls to valdiated Fields
        validated_data['business_logo'] = s3_logo_url
        validated_data['business_images'] = s3_image_urls
        validated_data['business_banner'] = s3_banner_urls

        with transaction.atomic():
            listing = Business.objects.create(**validated_data)
            BusinessBannerSerializer.banner_save(validated_data)
        # updating fields so normal user can become business user
        user.is_business = True
        user.previous_business = True
        user.save()
        return listing

    def update(self, instance, validated_data):
        '''
        Handle the update of listings and related fields.
        This method can be extended by child classes for custom logic.
        '''
        user = self.context['request'].user
        business_logo = validated_data.pop('business_logo', None)
        business_images = validated_data.pop('business_images', None)
        business_banner = validated_data.pop('business_banner', None)

        validated_data['business_logo'] = self.update_media(
            instance.business_logo,
            instance.business_category,
            business_logo,
            user.id,
            image_type='business_logo',
        )
        validated_data['business_images'] = self.update_media(
            instance.business_images,
            instance.business_category,
            business_images,
            user.id,
            image_type='business_images',
        )
        validated_data['business_banner'] = self.update_media(
            instance.business_banner,
            instance.business_category,
            business_banner,
            user.id,
            image_type='business_banner',
        )

        # Update other fields & Banner model as well
        banner_instance = AdminBusinessBanner.objects.filter(
            user_id=instance.user_id
        ).first()
        for attr, value in validated_data.items():
            current_value = getattr(instance, attr, None)
            if current_value != value:
                setattr(instance, attr, value)

            if banner_instance and hasattr(banner_instance, attr):
                second_model_value = getattr(banner_instance, attr)
                if second_model_value != value:
                    setattr(banner_instance, attr, value)

        # Update timestamps
        instance.updated_at = timezone.now()
        instance.save()
        banner_instance.updated_at = timezone.now()
        banner_instance.save()
        return instance

    def validate(self, data):
        request = self.context['request']
        admin_path = '/admin-panel/business/update'
        business_email = data.get('business_email')
        business_number = data.get('business_number')
        business_category = data.get('business_category')
        business_subcategory = data.get('business_subcategory')
        business_logo = data.get('business_logo', [])
        business_banner = data.get('business_banner', [])
        business_images = data.get('business_images', [])
        business_coordinates = data.get('business_coordinates')
        # if admin is updating, find the original user
        if request.path.startswith(admin_path):
            fetch_user = User.objects.filter(id=self.instance.user_id).first()

            if not fetch_user:
                raise ValidationError(
                    {'error': 'User not found for the given business'}
                )
            # update the user_id and user by finding the original user if admin is updating
            data['user_id'] = fetch_user.id
            self.context['request'].user = fetch_user
        else:
            user = self.context['request'].user
            data['user_id'] = user.id

        # validation checks for various fields of business
        if business_category not in CATEGORIES:
            raise ValidationError(
                {'Business category': f'Type must be in {list(CATEGORIES)}.'}
            )
        if business_subcategory not in CATEGORIES.get(business_category, []):
            raise ValidationError(
                {
                    'Business subcategory': f'Type must be in {CATEGORIES[business_category]}.'
                }
            )

        if (
            not isinstance(business_coordinates, list)
            or len(business_coordinates) != 2
        ):
            raise ValidationError(
                {
                    'business_coordinates': 'business_coordinates must be a list with [longitude, latitude].'
                }
            )
        lon, lat = business_coordinates
        if not (
            isinstance(lon, (int, float)) and isinstance(lat, (int, float))
        ):
            raise ValidationError(
                {
                    'business_coordinates': 'Longitude and latitude must be numbers.'
                }
            )

        # Ensure values are within valid longitude/latitude range
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValidationError(
                {
                    'business_coordinates': 'Longitude must be between -180 and 180, latitude must be between -90 and 90.'
                }
            )

        email_validation(business_email, 'Enter a valid business email address')
        validate_phone(business_number)
        validate_image(business_logo, 'Logo')
        validate_image(business_images, 'Images')
        validate_image(business_banner, 'Banner')

        # if admin is updating then we will check email & phone availability
        if request.path.startswith(admin_path):
            current_business = self.instance
            if current_business.business_email != business_email:
                self.check_duplicate(
                    'business_email',
                    business_email,
                    exclude_id=current_business.id,
                    error_msg='business email already exists',
                )
            if current_business.business_number != business_number:
                self.check_duplicate(
                    'business_number',
                    business_number,
                    exclude_id=current_business.id,
                    error_msg='business number already exists',
                )
        else:
            # If updating an existing business
            if self.instance:
                if self.instance.business_email != business_email:
                    self.check_duplicate(
                        'business_email',
                        business_email,
                        error_msg='business email already exists',
                    )
                if self.instance.business_number != business_number:
                    self.check_duplicate(
                        'business_number',
                        business_number,
                        error_msg='business number already exists',
                    )
            else:
                # Creating a new business
                self.check_duplicate(
                    'business_email',
                    business_email,
                    error_msg='business email already exists',
                )
                self.check_duplicate(
                    'business_number',
                    business_number,
                    error_msg='business number already exists',
                )

        data['created_at'] = timezone.now()
        data['updated_at'] = timezone.now()
        data['is_active'] = True

        return data


class BannerSearilizer(SQL_serializer.Serializer):
    '''
    Responsible for validating and serializing data related to business banners.
    '''

    user_id = SQL_serializer.IntegerField(required=False)
    business_email = SQL_serializer.CharField(required=True)
    business_name = SQL_serializer.CharField(required=True)
    business_banner = SQL_serializer.ListField(required=True)
    business_category = SQL_serializer.CharField(required=True)
    business_subcategory = SQL_serializer.CharField(required=True)

    def update(self, instance, validated_data):
        '''
        Handle the update of listings and related fields.
        '''
        validated_data.pop(
            'user_id', None
        )  # poped so it isnt updated in the process
        business_banner = validated_data.pop('business_banner', None)
        update_media = BusinessSerailizer()
        validated_data['business_banner'] = update_media.update_media(
            instance.business_banner,
            instance.business_category,
            business_banner,
            instance.user_id,
            image_type='business_banner',
        )

        # Update other fields
        for attr, value in validated_data.items():
            current_value = getattr(instance, attr, None)
            if current_value != value:
                if attr != 'business_banner':
                    raise ValidationError(
                        {'error': 'Only allowed to update business banner'}
                    )
                setattr(instance, attr, value)

        # Update timestamps
        instance.updated_at = timezone.now()
        instance.save()
        return instance
