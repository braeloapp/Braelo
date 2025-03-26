import uuid
from django.utils import timezone
from rest_framework_mongoengine import serializers
from azure.storage.blob import BlobServiceClient
from rest_framework.exceptions import ValidationError
from config import AZURE_ACCOUNT_NAME, AZURE_CONTAINER_NAME
from django.core.files.uploadedfile import InMemoryUploadedFile


from django.core.validators import validate_email
from users.models.business import Business
from helpers.constants import CATEGORIES
from admin_panel.models import AdminBusinessBanner


blob_service_client = BlobServiceClient.from_connection_string(
    "DefaultEndpointsProtocol=https;AccountName=braelos3;AccountKey=ODvt"
    "b8NuHRyWRsNR54wyp2lP0a7YGlM//NnhbkQKKv+JhX9E9Z+JXUSX56/sY7q0OxYPjidA5"
    "HL0+AStWzRAYA==;EndpointSuffix=core.windows.net"
)


def _validate_email(email, error_message):
    try:
        validate_email(email)
    except ValidationError:
        raise ValidationError({"email": error_message})


def validate_image(file, picture):
    # validate image to be in correct format for saving
    if isinstance(file, InMemoryUploadedFile):
        if not file.name.endswith(('.jpg', '.jpeg', '.png')):
            raise ValidationError({picture: f"Invalid {picture} format"})


class BusinessBannerSerializer(serializers.DocumentSerializer):

    class Meta:
        model = AdminBusinessBanner
        fields = '__all__'

    def upload_pictures(self, pictures, business_type, user_id):
        '''
        Handles the uploading of pictures to Azure Blob Storage.
        Returns a list of URLs for the uploaded pictures.
        '''
        s3_urls = []
        for picture in pictures:
            unique_name = f"{uuid.uuid4()}_{picture.name}"
            file_name = (
                f'business_banners/{business_type}/{user_id}/{unique_name}'
            )
            blob_client = blob_service_client.get_blob_client(
                container=AZURE_CONTAINER_NAME, blob=file_name
            )
            blob_client.upload_blob(picture, overwrite=True)

            picture_url = f'https://{AZURE_ACCOUNT_NAME}.blob.core.windows.net/{AZURE_CONTAINER_NAME}/{file_name}'
            s3_urls.append(picture_url)

        return s3_urls

    def validate(self, data):

        business_name = data.get('business_name')
        email = data.get('business_email')
        business_category = data.get('business_category')
        business_subcategory = data.get('business_subcategory')
        business_banner = data.get('business_banner')

        _validate_email(email, 'Enter a valid business email address')
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

        s3_logo_url = self.upload_pictures(
            business_banner, business_category, business.user_id
        )

        data['user_id'] = business.user_id
        data['business_banner'] = s3_logo_url
        data['created_at'] = timezone.now()

        return data

    def create(self, validated_data):
        return AdminBusinessBanner.objects.create(**validated_data)
