'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
Feedbacks endpoints serializers.
---------------------------------------------------
'''

from django.utils import timezone
from django.core.validators import validate_email
from rest_framework_mongoengine import serializers
from rest_framework.exceptions import ValidationError

from feedbacks.models import Feedbacks, Requests


class RequestsSerializer(serializers.DocumentSerializer):
    '''
    Serializer for user requests.
    '''

    class Meta:
        model = Requests
        fields = '__all__'

    def validate(self, data):
        validate_email(data.get('email'))
        user = self.context['request'].user
        data['user_id'] = user.id
        data['created_at'] = timezone.now()

        return data

    def create(self, validated_data):
        return Requests.objects.create(**validated_data)


class FeedbacksSerializer(serializers.DocumentSerializer):
    '''
    Serializer for feedbacks.
    '''

    class Meta:
        model = Feedbacks
        fields = '__all__'

    def validate(self, data):
        required_fields = ['Hate', 'Dislike', 'Neutral', 'Like', 'Love']
        user = self.context['request'].user

        if data.get('feedback') not in required_fields:
            raise ValidationError(
                {'review': f'feedback must be {required_fields}'}
            )
        data['user_id'] = user.id
        data['user_name'] = user.name
        data['created_at'] = timezone.now()

        return data

    def create(self, validated_data):
        user = self.context['request'].user
        feedback_instance = Feedbacks.objects.filter(user_id=user.id).first()

        # Update if already exists
        if feedback_instance:
            for key, value in validated_data.items():
                setattr(feedback_instance, key, value)
            feedback_instance.save()
            return feedback_instance

        return Feedbacks.objects.create(**validated_data)
