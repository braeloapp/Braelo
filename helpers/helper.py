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
from django.core.files.uploadedfile import InMemoryUploadedFile


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


def response(status, message, data, error=None):
    '''
    Returns a structured response with validation errors.
    :param status: Status code information. (dict)
    :param error: Error information. (dict)
    :param data: User information. (dict)
    :param message: Information about response. (dict)
    :return: Response object with formatted error details.
    '''

    def clean_data(data):
        resp = {}
        for key, value in data.items():
            if not isinstance(value, InMemoryUploadedFile):
                resp[key] = value
            else:
                resp[key] = value.name
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
    return JsonResponse(resp)


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
