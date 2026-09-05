'''Device token registration. Identity always comes from the JWT user.'''

from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from users.models.devices import UserDeviceToken


class DeviceTokenSerializer(serializers.Serializer):
    token = serializers.CharField(required=True, max_length=4096)
    platform = serializers.ChoiceField(choices=['android', 'ios'])
    previous_token = serializers.CharField(
        required=False, allow_blank=True, max_length=4096
    )

    def validate_token(self, value):
        token = (value or '').strip()
        if not token:
            raise ValidationError('Token is required.')
        return token

    def save(self):
        user = self.context['request'].user
        platform = self.validated_data['platform']
        token = self.validated_data['token']
        previous = (self.validated_data.get('previous_token') or '').strip()
        if previous and previous != token:
            UserDeviceToken.objects(user_id=user.id, token=previous).delete()

        stolen = UserDeviceToken.objects(token=token).first()
        if stolen and stolen.user_id != user.id:
            stolen.delete()

        device = UserDeviceToken.objects(token=token).first()
        if device:
            device.user_id = user.id
            device.platform = platform
            device.email = user.email or None
            device.save()
            return device

        return UserDeviceToken.objects.create(
            user_id=user.id,
            platform=platform,
            token=token,
            email=user.email or None,
        )


class DeleteDeviceTokenSerializer(serializers.Serializer):
    token = serializers.CharField(required=False, allow_blank=True, max_length=4096)
