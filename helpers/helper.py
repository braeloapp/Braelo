'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
Helper functions file.
---------------------------------------------------
'''

from django.http import JsonResponse
from rest_framework_simplejwt.tokens import RefreshToken
from django.core.files.uploadedfile import UploadedFile


def _is_file_like(value):
    if isinstance(value, UploadedFile):
        return True
    # Temp file wrappers may not match UploadedFile in all edge cases
    return hasattr(value, 'read') and hasattr(value, 'name') and callable(getattr(value, 'read', None))


def get_error_details(error_info):
    '''
    Gets error message through exceptions.
    :param error_info: exception error. (dict or list)
    :return: error information. (string)
    '''

    if isinstance(error_info, list):
        return f'Error: {str(error_info[0])}' if error_info else 'Unknown error'

    elif isinstance(error_info, dict):
        for key, errors in error_info.items():
            if isinstance(errors, list):
                return (
                    f'{key}: {str(errors[0])}'
                    if errors
                    else f'{key}: Unknown error'
                )
            else:
                return f'{key}: {str(errors)}'

    return 'Unknown error format'


def response(status, message, data, error=None, http_status=None, retry_after=None):
    '''
    Returns a structured response with validation errors.

    HTTP status stays 200 unless ``http_status`` is set. Existing Flutter
    and admin clients read ``status`` from the JSON body. Rate limits and
    health probes are the exception and set a real HTTP status.
    '''

    def _sanitize_for_json(value):
        if isinstance(value, UploadedFile) or _is_file_like(value):
            return getattr(value, 'name', None) or '<upload>'
        if isinstance(value, (list, tuple)):
            return [_sanitize_for_json(v) for v in value]
        if isinstance(value, dict):
            return {k: _sanitize_for_json(v) for k, v in value.items()}
        return value

    def clean_data(data):
        resp = {}
        for key, value in data.items():
            resp[key] = _sanitize_for_json(value)
        return resp

    if isinstance(data, list) and error:
        data = [clean_data(item) for item in data]
    elif isinstance(data, dict):
        data = clean_data(data)

    resp = {
        'status': status,
        'message': message,
        'error': error,
        'data': data,
    }
    payload = JsonResponse(resp)
    if http_status is not None:
        payload.status_code = int(http_status)
    if retry_after is not None:
        payload['Retry-After'] = str(int(retry_after))
    return payload


def get_token(user):
    '''
    Generates JWT token for user.
    :param user: user information. (dict)
    :return: JWT token. (dict)
    '''
    # Generate JWT token after user creation
    refresh = RefreshToken.for_user(user)
    token_data = {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }
    return token_data
