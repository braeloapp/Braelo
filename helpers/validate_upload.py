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
from django.core.files.uploadedfile import UploadedFile

from helpers.azure import blob_service_client


def _upload_body_from_django_file(picture) -> bytes:
    """
    Read upload into bytes before Azure upload_blob.

    Passing TemporaryUploadedFile / BufferedRandom streams to the Azure SDK can
    trigger \"cannot pickle 'BufferedRandom' instances\" on some platforms.

    Always call ``UploadedFile.close()`` after reading so Django's Windows
    ``TemporaryFile`` is finalized in normal code flow. If it is only closed from
    ``__del__`` during GC, ``close_called`` can be missing and stderr shows
    AttributeError (harmless but noisy).
    """
    try:
        if hasattr(picture, 'read'):
            if hasattr(picture, 'seek'):
                try:
                    picture.seek(0)
                except (OSError, AttributeError, ValueError, TypeError):
                    pass
            data = picture.read()
            if isinstance(data, str):
                return data.encode('utf-8')
            return bytes(data)
        if isinstance(picture, (bytes, bytearray)):
            return bytes(picture)
        raise TypeError(f'Unsupported upload type: {type(picture)!r}')
    finally:
        if isinstance(picture, UploadedFile):
            try:
                picture.close()
            except Exception:
                pass


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
        if isinstance(picture, UploadedFile) or hasattr(picture, 'read'):
            body = _upload_body_from_django_file(picture)
            blob_client.upload_blob(body, overwrite=True)
        else:
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


ALLOWED_IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png')
ALLOWED_IMAGE_CONTENT_TYPES = {
    'image/jpeg',
    'image/jpg',
    'image/png',
}
MAX_IMAGE_BYTES = 8 * 1024 * 1024


def validate_image(file, picture):
    # validate image to be in correct format for saving
    if isinstance(file, UploadedFile):
        name = (getattr(file, 'name', None) or '').lower()
        if not name.endswith(ALLOWED_IMAGE_EXTENSIONS):
            raise ValidationError({picture: f'Invalid {picture} format'})
        content_type = (getattr(file, 'content_type', None) or '').lower()
        if content_type and content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
            raise ValidationError({picture: f'Invalid {picture} type'})
        size = getattr(file, 'size', None)
        if size is not None and size > MAX_IMAGE_BYTES:
            raise ValidationError({picture: f'{picture} exceeds 8MB limit'})
