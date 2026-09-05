'''
Admin-path authorization helpers.

Shared mobile/admin views must not trust the URL prefix alone. Any request
under /admin-panel/ requires an authenticated staff or superuser.
'''

from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission

ADMIN_PATH_PREFIX = '/admin-panel'


def is_admin_path(request) -> bool:
    path = getattr(request, 'path', '') or ''
    return path.startswith(ADMIN_PATH_PREFIX)


def is_staff_user(user) -> bool:
    return bool(
        user
        and getattr(user, 'is_authenticated', False)
        and (getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False))
    )


def admin_role(user) -> str:
    if not is_staff_user(user):
        return 'client'
    if getattr(user, 'is_superuser', False):
        return 'super_admin'
    return 'admin'


def require_staff(request):
    if not is_staff_user(getattr(request, 'user', None)):
        raise ValidationError({'error': 'Admin access required.'})
    return request.user


class DenyAdminPathUnlessStaff(BasePermission):
    '''
    Non-admin URLs are unchanged. Admin-panel URLs require staff/superuser.
    '''

    def has_permission(self, request, view):
        if not is_admin_path(request):
            return True
        return is_staff_user(request.user)
