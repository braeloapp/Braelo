'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
Serializer file for saved item Listings based endpoints
---------------------------------------------------
'''

from bson import ObjectId
from helpers import response, status
from bson.errors import InvalidId
from django.utils import timezone
from listings.models import SavedItem
from helpers.constants import CATEGORIES
from helpers.normalize import resolve_category, resolve_subcategory
from rest_framework_mongoengine import serializers
from rest_framework.exceptions import ValidationError
from django.core.exceptions import ObjectDoesNotExist


from helpers.model_map import MODEL_MAP


class SavedItemSerializer(serializers.DocumentSerializer):
    class Meta:
        model = SavedItem

    def validate_id(self, value):
        """
        Ensure the `id` field is a valid ObjectId.
        """
        try:
            ObjectId(value)  # Validate the format of the provided ID
        except InvalidId:
            raise ValidationError("Invalid listing ID format.")
        return value

    def validate(self, data):
        '''
        Additional validation for the SavedItem.
        '''
        user = self.context['request'].user
        data['user_id'] = user.id

        # Validate category (case/format-insensitive)
        category = data.get('category')
        subcategory = data.get('subcategory')
        listing_id = data.get('listing_id')
        canonical_category = resolve_category(category)
        if canonical_category is None:
            raise ValidationError(
                {
                    'category': f'Invalid category. Available categories: {list(CATEGORIES.keys())}'
                }
            )
        category = canonical_category
        data['category'] = canonical_category
        if subcategory:
            canonical_subcategory = resolve_subcategory(category, subcategory)
            if canonical_subcategory is None:
                raise ValidationError(
                    {
                        'subcategory': f'subcategories should be {CATEGORIES[category]}'
                    }
                )
            subcategory = canonical_subcategory
            data['subcategory'] = canonical_subcategory

        # Ensure the listing exists
        validation_data = {
            'id': listing_id,
            'category': category,
            'subcategory': subcategory,
            'title': data['title'],
            'pictures': data['pictures'],
        }
        model = MODEL_MAP.get(category)
        if not model.objects.filter(**validation_data):
            raise ValidationError(
                {'listings': 'Data Invalid or no matching listings found'}
            )

        # Add `saved_at` timestamp
        data['saved_at'] = timezone.now()
        return data

    def create(self, validated_data):
        '''
        Create a SavedItem document.
        '''
        listing_id = validated_data['listing_id']
        user_id = validated_data['user_id']
        if SavedItem.objects(listing_id=listing_id, user_id=user_id).first():
            raise ValidationError({'listings': 'Already Saved'})

        return SavedItem.objects.create(**validated_data)
