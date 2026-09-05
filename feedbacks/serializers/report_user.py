from django.utils import timezone
from rest_framework_mongoengine import serializers
from rest_framework.exceptions import ValidationError

from feedbacks.models import ReportMessage
from users.models import User


class ReportMessageSerializer(serializers.DocumentSerializer):
    class Meta:
        model = ReportMessage
        fields = '__all__'

    def validate(self, data):
        required_fields = [
            'Offensive',
            'Scam',
            'Threatening',
            'Unwanted',
            'Other',
        ]
        user = self.context['request'].user
        data['reported_by'] = user.id
        reported_to = data.get('reported_to')
        report_checkbox = data.get('report_checkbox')

        if not reported_to:
            raise ValidationError({'Error': 'Reported_User_id is Missing'})
        try:
            reported_to = int(reported_to)
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                {'reported_to': 'reported_to must be a user id.'}
            ) from exc
        if reported_to == user.id:
            raise ValidationError({'reported_to': 'You cannot report yourself.'})
        if not User.objects.filter(id=reported_to).exists():
            raise ValidationError({'reported_to': 'User does not exist.'})
        data['reported_to'] = reported_to

        if report_checkbox not in required_fields:
            raise ValidationError(
                {
                    'report_checkbox': f'Invalid Type. Report Must be {required_fields}'
                }
            )
        data['created_at'] = timezone.now()
        return data

    def create(self, validated_data):
        return ReportMessage.objects.create(**validated_data)
