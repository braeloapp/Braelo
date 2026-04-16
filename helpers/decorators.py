'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
braelo decorators file.
---------------------------------------------------
'''

from functools import wraps

from rest_framework import status
from pymongo.errors import PyMongoError
from rest_framework.exceptions import ValidationError
from sqlite3 import OperationalError as SQLITE_ERROR
from helpers import get_error_details, response


def _safe_request_data(request):
    """Never echo raw multipart file objects into JsonResponse (pickle / JSON issues)."""
    try:
        return request.data
    except Exception:
        return {}


def handle_exceptions(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ValidationError as err:
            error = get_error_details(err.detail)
            return response(
                status=status.HTTP_400_BAD_REQUEST,
                message='Validation Error',
                data=_safe_request_data(args[1]),
                error=error,
            )
        except SQLITE_ERROR as err:
            return response(
                status=status.HTTP_400_BAD_REQUEST,
                message='Database failure',
                data=_safe_request_data(args[1]),
                error=str(err),
            )
        except PyMongoError as err:
            return response(
                status=status.HTTP_400_BAD_REQUEST,
                message='Mongo DB failure',
                data=_safe_request_data(args[1]),
                error=str(err),
            )
        except Exception as err:
            return response(
                status=status.HTTP_400_BAD_REQUEST,
                message='Exception',
                data=_safe_request_data(args[1]),
                error=str(err),
            )

    return wrapper
