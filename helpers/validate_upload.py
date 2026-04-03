'''
---------------------------------------------------
Project:        Braelo
Date:           Dec 20, 2024
Author:         Faizan
---------------------------------------------------

Description:
helper file for validating and uplaoding images on Azure
---------------------------------------------------
'''

import uuid
import phonenumbers
from django.core.validators import validate_email
from rest_framework.exceptions import ValidationError
from config import AZURE_ACCOUNT_NAME, AZURE_CONTAINER_NAME
from django.core.files.uploadedfile import InMemoryUploadedFile

from helpers.azure import blob_service_client


def upload_pictures(pictures, business_type, user_id, image_type='business'):
    '''
    Handles the uploading of pictures to Azure Blob Storage.
    Returns a list of URLs for the uploaded pictures.
    '''
    s3_urls = []
    for picture in pictures:
        file_name = f'{image_type}/{business_type}/{user_id}/{uuid.uuid4()}.png'
        blob_client = blob_service_client.get_blob_client(
            container=AZURE_CONTAINER_NAME, blob=file_name
        )
        blob_client.upload_blob(picture, overwrite=True)

        picture_url = f'https://{AZURE_ACCOUNT_NAME}.blob.core.windows.net/{AZURE_CONTAINER_NAME}/{file_name}'
        s3_urls.append(picture_url)

    return s3_urls


def email_validation(email, error_message):
    try:
        validate_email(email)
    except ValidationError:
        raise ValidationError({'email': error_message})


def validate_phone(phone):
    try:
        # Parsing phone number
        parsed_number = phonenumbers.parse(phone, None)
        # Checking if the parsed number is a valid number
        if not phonenumbers.is_valid_number(parsed_number):
            raise ValidationError({'error': 'This is not valid phone number.'})
    except phonenumbers.NumberParseException:
        raise ValidationError({'error': 'This is not valid phone number.'})


def validate_image(file, picture):
    # validate image to be in correct format for saving
    if isinstance(file, InMemoryUploadedFile):
        if not file.name.endswith(('.jpg', '.jpeg', '.png')):
            raise ValidationError({picture: f'Invalid {picture} format'})
