"""DRF exception handler that maps RateLimitExceeded to the Braelo envelope."""

from rest_framework.views import exception_handler

from helpers.helper import response
from users.services.rate_limit import RateLimitExceeded


def braelo_exception_handler(exc, context):
    if isinstance(exc, RateLimitExceeded):
        return response(
            status=429,
            message="Too many requests",
            data={},
            error=str(exc),
            http_status=429,
            retry_after=exc.retry_after,
        )
    return exception_handler(exc, context)
