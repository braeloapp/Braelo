'''
Optional JWT auth: invalid / missing / placeholder tokens become anonymous
instead of hard 401. Use on public-read endpoints that still want click
analytics when a valid user is logged in.
'''

from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError


class OptionalJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        header = self.get_header(request)
        if header is None:
            return None

        raw_token = self.get_raw_token(header)
        if raw_token is None:
            return None

        try:
            token_text = raw_token.decode('utf-8').strip().lower()
        except Exception:
            token_text = ''
        if token_text in ('', 'null', 'undefined', 'none'):
            return None

        try:
            validated_token = self.get_validated_token(raw_token)
            return self.get_user(validated_token), validated_token
        except (InvalidToken, TokenError, AuthenticationFailed):
            return None
