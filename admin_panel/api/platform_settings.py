'''Platform settings — force update, listing cap, auth toggles.'''

from rest_framework.permissions import IsAdminUser, AllowAny
from rest_framework.views import APIView
from rest_framework import status

from helpers import handle_exceptions, response
from admin_panel.models import PlatformSettings
from admin_panel.services.audit import record_admin_action


def serialize_settings(obj):
    return {
        'max_active_listings_non_business': obj.max_active_listings_non_business,
        'search_min_chars': obj.search_min_chars,
        'default_explore_radius_km': obj.default_explore_radius_km,
        'min_ios_version': obj.min_ios_version,
        'min_android_version': obj.min_android_version,
        'force_update': obj.force_update,
        'phone_auth_enabled': obj.phone_auth_enabled,
        'google_auth_enabled': obj.google_auth_enabled,
        'apple_auth_enabled': obj.apple_auth_enabled,
        'updated_at': obj.updated_at.isoformat() if obj.updated_at else None,
    }


class PlatformSettingsAdmin(APIView):
    permission_classes = [IsAdminUser]

    @handle_exceptions
    def get(self, request):
        obj = PlatformSettings.get_solo()
        return response(
            status=status.HTTP_200_OK,
            message='Platform settings fetched',
            data=serialize_settings(obj),
        )

    @handle_exceptions
    def put(self, request):
        obj = PlatformSettings.get_solo()
        previous = serialize_settings(obj)
        data = request.data or {}

        int_fields = (
            'max_active_listings_non_business',
            'search_min_chars',
            'default_explore_radius_km',
        )
        bool_fields = (
            'force_update',
            'phone_auth_enabled',
            'google_auth_enabled',
            'apple_auth_enabled',
        )
        str_fields = ('min_ios_version', 'min_android_version')

        for field in int_fields:
            if field in data and data[field] is not None:
                setattr(obj, field, max(0, int(data[field])))
        for field in bool_fields:
            if field in data:
                setattr(obj, field, bool(data[field]))
        for field in str_fields:
            if field in data and data[field] is not None:
                setattr(obj, field, str(data[field])[:32])

        obj.save()
        new = serialize_settings(obj)
        record_admin_action(
            actor=request.user,
            action='settings',
            target_type='platform_settings',
            target_id='1',
            summary='Updated platform settings',
            previous_state=previous,
            new_state=new,
        )
        return response(
            status=status.HTTP_200_OK,
            message='Platform settings updated',
            data=new,
        )


class PlatformSettingsPublic(APIView):
    '''Mobile-readable subset (no secrets).'''

    permission_classes = [AllowAny]

    @handle_exceptions
    def get(self, request):
        obj = PlatformSettings.get_solo()
        return response(
            status=status.HTTP_200_OK,
            message='Platform config',
            data={
                'max_active_listings_non_business': obj.max_active_listings_non_business,
                'search_min_chars': obj.search_min_chars,
                'default_explore_radius_km': obj.default_explore_radius_km,
                'min_ios_version': obj.min_ios_version,
                'min_android_version': obj.min_android_version,
                'force_update': obj.force_update,
                'phone_auth_enabled': obj.phone_auth_enabled,
                'google_auth_enabled': obj.google_auth_enabled,
                'apple_auth_enabled': obj.apple_auth_enabled,
            },
        )
