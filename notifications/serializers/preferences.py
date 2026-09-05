from rest_framework import serializers

from notifications.services.preferences import PREFERENCE_KEYS


class NotificationPreferenceSerializer(serializers.Serializer):
    messages = serializers.BooleanField(required=False)
    listing_activity = serializers.BooleanField(required=False)
    business_activity = serializers.BooleanField(required=False)
    marketing = serializers.BooleanField(required=False)
    system_security = serializers.BooleanField(required=False)
    admin_announcements = serializers.BooleanField(required=False)

    def validate(self, attrs):
        if not any(key in attrs for key in PREFERENCE_KEYS):
            raise serializers.ValidationError(
                {'detail': 'At least one preference field is required.'}
            )
        return attrs
