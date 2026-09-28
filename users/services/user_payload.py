"""Small user fields reused across auth responses."""


def public_profile_picture(user):
    if user is None:
        return None
    url = (getattr(user, 'profile_picture', None) or '').strip()
    return url or None
