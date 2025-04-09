'''
---------------------------------------------------
Project:        Braelo
Date:           March 20, 2025
Author:         Faizan
---------------------------------------------------

Description:
Serializer for business banners
---------------------------------------------------
'''

from django.utils import timezone
from rest_framework_mongoengine import serializers
from rest_framework.exceptions import ValidationError

from helpers.constants import CATEGORIES
from users.models.business import Business
from admin_panel.models import AdminBusinessBanner
from helpers import upload_pictures, email_validation, validate_image


class BusinessBannerSerializer(serializers.DocumentSerializer):

    class Meta:
        model = AdminBusinessBanner
        fields = '__all__'

    def validate(self, data):

        business_name = data.get('business_name')
        email = data.get('business_email')
        business_category = data.get('business_category')
        business_subcategory = data.get('business_subcategory')
        business_banner = data.get('business_banner')

        email_validation(email, 'Enter a valid business email address')
        validate_image(business_banner, 'Banner')
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

        business = Business.objects.filter(
            business_name=business_name,
            business_email=email,
            business_category=business_category,
            business_subcategory=business_subcategory,
        ).first()

        if not business:
            raise ValidationError({'Error': 'No business found'})

        s3_logo_url = upload_pictures(
            business_banner,
            business_category,
            business.user_id,
            image_type='business_banner',
        )

        data['user_id'] = business.user_id
        data['business_banner'] = s3_logo_url
        data['created_at'] = timezone.now()
        data['updated_at'] = timezone.now()

        return data

    def create(self, validated_data):
        return AdminBusinessBanner.objects.create(**validated_data)

    @staticmethod
    def banner_save(data):
        '''
        saves banner when business is created in banner collection
        '''
        try:
            required_fields = [
                'user_id',
                'business_email',
                'business_name',
                'business_banner',
                'business_category',
                'business_subcategory',
                'created_at',
            ]
            missing_fields = [
                field for field in required_fields if field not in data
            ]

            if missing_fields:
                raise ValidationError(
                    f'Missing required fields: {", ".join(missing_fields)}'
                )
            obj = {
                'user_id': data['user_id'],
                'business_name': data['business_name'],
                'business_email': data['business_email'],
                'business_banner': data['business_banner'],
                'business_category': data['business_category'],
                'business_subcategory': data['business_subcategory'],
                'created_at': data['created_at'],
            }
            AdminBusinessBanner.objects.create(**obj)

        except ValidationError as ve:
            raise ve

        except Exception as e:
            raise ValidationError(f'Failed to save Banner :  {e}')
