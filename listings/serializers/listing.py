'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
Listing (Upsert) Serializers.
---------------------------------------------------
'''

from django.db import transaction
from django.utils import timezone
from azure.storage.blob import BlobServiceClient
from rest_framework.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile


from helpers import blob_service_client
from users.models import User
from rest_framework_mongoengine import serializers
from rest_framework import serializers as SE
from helpers.constants import (
    CATEGORIES,
    USER_LISTINGS_THRESHOLD,
    KEYWORDS_LIMIT,
)
from helpers.listsync import ListSynchronize
from config import AZURE_ACCOUNT_NAME, AZURE_CONTAINER_NAME
from listings.models import (
    ElectronicsListing,
    EventsListing,
    FashionListing,
    FurnitureListing,
    JobsListing,
    RealEstateListing,
    ServicesListing,
    SportsHobbyListing,
    VehicleListing,
    KidsListing,
    SavedItem,
)

from users.models import Business


class Serializer(serializers.DocumentSerializer):
    is_saved = SE.SerializerMethodField()

    class Meta:
        abstract = True

    def get_is_saved(self, obj):
        """
        Check if the listing is saved by the current user.
        """
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False

        user = request.user
        # Assuming SavedItem has fields: `user_id` and `listing_id`
        return bool(SavedItem.objects(user_id=user.id, listing_id=obj.id))

    def upload_pictures(self, pictures, category, user):
        '''
        Handles the uploading of pictures to Azure Blob Storage.
        Returns a list of URLs for the uploaded pictures.
        '''
        if pictures is None:
            pictures = []
        elif not isinstance(pictures, (list, tuple)):
            pictures = [pictures]
        s3_urls = []
        for picture in pictures:
            file_name = f'listings/{category}/{user.id}/{picture.name}'
            blob_client = blob_service_client.get_blob_client(
                container=AZURE_CONTAINER_NAME, blob=file_name
            )
            blob_client.upload_blob(picture, overwrite=True)

            picture_url = f'https://{AZURE_ACCOUNT_NAME}.blob.core.windows.net/{AZURE_CONTAINER_NAME}/{file_name}'
            s3_urls.append(picture_url)

        return s3_urls

    def create(self, validated_data):
        '''
        Handle the creation of listings and picture uploads.
        This method can be extended by child classes for custom logic.
        '''
        self.context['is_update'] = False
        pictures = validated_data.pop('pictures', [])
        category = validated_data.get('category')
        user = self.context['request'].user
        # Upload pictures
        s3_urls = self.upload_pictures(pictures, category, user)
        # Add URLs to validated data
        validated_data['pictures'] = s3_urls

        with transaction.atomic():
            listing = self.Meta.model.objects.create(**validated_data)
            ListSynchronize.listsync(validated_data, listing.id)
        return listing

    def update(self, instance, validated_data):
        '''
        Handle the update of listings and related fields.
        This method can be extended by child classes for custom logic.
        '''

        admin_path = "/admin-panel"
        pictures = validated_data.pop('pictures', None)
        user = self.context['request'].user
        admin = self.context['request'].path.startswith(admin_path) and (
            user.is_staff or user.is_superuser
        )
        if instance.user_id != user.id:
            if not admin:
                raise ValidationError(
                    {'Error': 'You cannot change someone else listings'}
                )

        if pictures:
            # Delete already existed ones
            if instance.pictures:
                for picture_url in instance.pictures:
                    # Extract the blob name from the URL
                    blob_name = picture_url.split(f'{AZURE_CONTAINER_NAME}/')[
                        -1
                    ]
                    blob_client = blob_service_client.get_blob_client(
                        container=AZURE_CONTAINER_NAME, blob=blob_name
                    )
                    blob_client.delete_blob()
                    # Upload New ones
            s3_urls = self.upload_pictures(pictures, instance.category, user)

            # Replace existing picture URLs
            validated_data['pictures'] = s3_urls

        # Update other fields
        user_id = validated_data.get('user_id')
        validated_data.pop('user_id', None)
        for attr, value in validated_data.items():
            current_value = getattr(instance, attr, None)
            if current_value != value:
                setattr(instance, attr, value)

        # Update timestamps
        instance.updated_at = timezone.now()
        instance.save()
        # Adding it back to send to listysync
        validated_data['user_id'] = user_id
        # Update list sync collection
        ListSynchronize.listsync(
            validated_data, instance.id, update=True, admin=admin
        )
        return instance

    def validate(self, data):
        '''
        Common validation logic for listings.
        Ensures category and subcategory validation and user association.
        '''
        user = self.context['request'].user
        data['from_business'] = data.get('from_business')
        data['user_id'] = user.id
        category = data.get('category')
        subcategory = data.get('subcategory')
        year = data.get('year')
        keywords = data.get('keywords')
        status = data.get('is_active')
        listing_coordinates = data.get('listing_coordinates')
        user_status = user

        # Check if this is an update call
        is_update = self.context.get('is_update', False)

        # coordinates validation
        if (
            not isinstance(listing_coordinates, list)
            or len(listing_coordinates) != 2
        ):
            raise ValidationError(
                {
                    'listing_coordinates': 'listing_coordinates must be a list with [longitude, latitude].'
                }
            )
        lon, lat = listing_coordinates
        if not (
            isinstance(lon, (int, float)) and isinstance(lat, (int, float))
        ):
            raise ValidationError(
                {
                    'listing_coordinates': 'Longitude and latitude must be numbers.'
                }
            )

        # Ensure values are within valid longitude/latitude range
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValidationError(
                {
                    'listing_coordinates': 'Longitude must be between -180 and 180, latitude must be between -90 and 90.'
                }
            )
        if data['from_business'] not in (True, False):
            raise ValidationError({'from_business': 'Must be ("True","False")'})
        if data['from_business']:
            if not Business.objects.filter(user_id=user.id).first():
                raise ValidationError({'Error': 'Create Business First'})
        # Check keywords limit
        if len(keywords) > KEYWORDS_LIMIT:
            raise ValidationError({'Keywords': 'Limit is 10'})
        # If it's not an update, Increament in Listings Count
        if not is_update:
            if (
                not data['from_business']
                and user_status.listings_count == USER_LISTINGS_THRESHOLD
            ):
                raise ValidationError({'Listings': 'Normal User Limit Reached'})
            user_status.listings_count += 1
            user_status.save()
        # Validate category and subcategory
        if category != self.Meta.category:
            raise ValidationError(
                {'category': f'categories should be {self.Meta.category}'}
            )
        if subcategory and subcategory not in CATEGORIES.get(category, []):
            raise ValidationError(
                {
                    'subcategory': f'subcategories should be {CATEGORIES[category]}'
                }
            )
        if year:
            current_year = timezone.now().year
            if year < 1886 or year > current_year:
                raise ValidationError(
                    {'year': f'Year must be between 1886 and {current_year}.'}
                )
        data['is_active'] = True if status else False
        pictures = data.get('pictures', [])
        if pictures is None:
            pictures = []
        elif not isinstance(pictures, (list, tuple)):
            pictures = [pictures]
        data['pictures'] = pictures
        for picture in pictures:
            if isinstance(picture, UploadedFile):
                if not picture.name.lower().endswith(('.jpg', '.jpeg', '.png')):
                    raise ValidationError(
                        {'pictures': 'Invalid picture format'}
                    )

        # Timestamps
        data['created_at'] = timezone.now()
        data['updated_at'] = timezone.now()
        return data


class ElectronicsSerializer(Serializer):
    class Meta:
        model = ElectronicsListing
        fields = '__all__'
        category = 'electronics'


class EventsSerializer(Serializer):
    class Meta:
        model = EventsListing
        fields = '__all__'
        category = 'events'


class FashionSerializer(Serializer):
    class Meta:
        model = FashionListing
        fields = '__all__'
        category = 'fashion'


class FurnitureSerializer(Serializer):
    class Meta:
        model = FurnitureListing
        fields = '__all__'
        category = 'furniture'


class JobsSerializer(Serializer):
    class Meta:
        model = JobsListing
        fields = '__all__'
        category = 'jobs'


class KidsSerializer(Serializer):
    class Meta:
        model = KidsListing
        fields = '__all__'
        category = 'kids'


class RealEstateSerializer(Serializer):
    class Meta:
        model = RealEstateListing
        category = 'realestate'
        fields = '__all__'


class ServicesSerializer(Serializer):
    class Meta:
        model = ServicesListing
        fields = '__all__'
        category = 'Services'


class SportsHobbySerializer(Serializer):
    class Meta:
        model = SportsHobbyListing
        fields = '__all__'
        category = 'sportsandhobby'


class VehicleSerializer(Serializer):
    class Meta:
        model = VehicleListing
        fields = '__all__'
        category = 'Vehicles'


# Update serializers


class ElectronicsUpdateSerializer(Serializer):
    class Meta:
        model = ElectronicsListing
        fields = '__all__'
        category = 'electronics'


class EventsUpdateSerializer(Serializer):
    class Meta:
        model = EventsListing
        fields = '__all__'
        category = 'events'


class FashionUpdateSerializer(Serializer):
    class Meta:
        model = FashionListing
        fields = '__all__'
        category = 'fashion'


class FurnitureUpdateSerializer(Serializer):
    class Meta:
        model = FurnitureListing
        fields = '__all__'
        category = 'furniture'


class JobsUpdateSerializer(Serializer):
    class Meta:
        model = JobsListing
        fields = '__all__'
        category = 'jobs'


class KidsUpdateSerializer(Serializer):
    class Meta:
        model = KidsListing
        fields = '__all__'
        category = 'kids'


class RealEstateUpdateSerializer(Serializer):
    class Meta:
        model = RealEstateListing
        category = 'realestate'
        fields = '__all__'


class ServicesUpdateSerializer(Serializer):
    class Meta:
        model = ServicesListing
        fields = '__all__'
        category = 'Services'


class SportsHobbyUpdateSerializer(Serializer):
    class Meta:
        model = SportsHobbyListing
        fields = '__all__'
        category = 'sportsandhobby'


class VehicleUpdateSerializer(Serializer):
    class Meta:
        model = VehicleListing
        fields = '__all__'
        category = 'Vehicles'
