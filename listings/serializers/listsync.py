'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
Serializer file for list sync Listings based endpoints
---------------------------------------------------
'''

from helpers.models.listsync import ListSync
from rest_framework import serializers as SE
from rest_framework_mongoengine import serializers

from listings.models import SavedItem
from listings.services.taxonomy import apply_taxonomy_display_names


class ListsyncSerializer(serializers.DocumentSerializer):
    is_saved = SE.SerializerMethodField()

    class Meta:
        model = ListSync
        fields = '__all__'

    def get_is_saved(self, obj):
        """
        Check if the listing is saved by the current user.
        """
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False

        user = request.user
        listing_id = getattr(obj, 'listing_id', None) or obj.id
        return bool(SavedItem.objects(user_id=user.id, listing_id=listing_id))

    def to_representation(self, instance):
        '''
        Modify 'fields attribute' to exclude NULL fields of Mongo doc
        '''
        modify_fields = super().to_representation(instance)

        # Remove values from fields if price or salary is NULL
        if instance.price is None:
            modify_fields.pop('price', None)
        if instance.salary_range is None:
            modify_fields.pop('salary_range', None)
        apply_taxonomy_display_names(modify_fields)
        return modify_fields
