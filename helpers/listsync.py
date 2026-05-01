'''
---------------------------------------------------
Project:        Braelo
Date:           Aug 14, 2024
Author:         Hamid
---------------------------------------------------

Description:
Listing synchronization with listsync collection helper class.
---------------------------------------------------
'''

from mongoengine import DoesNotExist, OperationError
from rest_framework.exceptions import ValidationError


class ListSynchronize:
    '''
    List synchronization helper class.
    '''

    @staticmethod
    def flip_status(listing_id, status, user_id, model=None):
        '''
        flip status for certain list.
        '''
        from helpers import ListSync

        model = model or ListSync
        filter_by = 'listing_id' if model == ListSync else 'id'

        try:
            filter_by = 'listing_id' if model == ListSync else 'id'
            # if category or user_id or listing _id is not correct
            active_status = model.objects(
                **{filter_by: listing_id, 'user_id': user_id}
            ).first()

            if not active_status:
                if model == ListSync:
                    detail = (
                        'No ListSync row for this listing_id and your user. '
                        'The listing may need to be re-saved or synced to listsync.'
                    )
                else:
                    detail = (
                        'No listing in this category for this id and your user. '
                        'You must be logged in as the listing owner (user_id on the listing).'
                    )
                raise ValidationError({'Listings': detail})
            if active_status.is_active == status:
                raise ValidationError(
                    {'Status': f'The status is already set to {status}'}
                )
            result = model.objects(**{filter_by: listing_id}).update_one(
                set__is_active=status
            )
            if result == 0:
                raise DoesNotExist(
                    f'{model.__name__}: listing_id {listing_id} does not exist'
                )
            return True
        except OperationError as oe:
            raise OperationError(f'flip_status: Operation error: {oe}')

    @staticmethod
    def listsync(data, _id, update=False, admin=False):
        '''
        Save listing doc to listsync collection.
        '''
        from helpers import ListSync

        required_fields = [
            'user_id',
            'category',
            'subcategory',
            'keywords',
            'listing_coordinates',
            'title',
            'from_business',
            'created_at',
        ]
        missing_fields = [
            field for field in required_fields if field not in data
        ]

        if missing_fields:
            raise ValidationError(
                f'Missing required fields: {", ".join(missing_fields)}'
            )
        obj = {
            'user_id': data['user_id'],
            'listing_id': str(_id),
            'category': data['category'],
            'subcategory': data['subcategory'],
            'listing_coordinates': data['listing_coordinates'],
            'title': data['title'],
            'keywords': data['keywords'],
            'pictures': data['pictures'],
            'from_business': data['from_business'],
            'created_at': data['created_at'],
        }
        price = (
            data.get('service_fee')
            or data.get('ticket_price')
            or data.get('price')
        )
        obj['price'] = price

        # Price range
        if data.get('salary_range'):
            obj['salary_range'] = data['salary_range']
        try:
            if update:
                obj.pop('user_id', None)
                update_fields = {
                    f'set__{key}': value
                    for key, value in obj.items()
                    if value is not None
                }
                query = {'listing_id': str(_id)}
                if not admin:
                    query['user_id'] = data['user_id']

                result = ListSync.objects(**query).modify(
                    upsert=False, new=True, **update_fields
                )

                if not result:
                    raise ValidationError(
                        f'No listing found to update with ID: {_id}'
                    )
            else:
                list_sync_entry = ListSync(**obj)
                list_sync_entry.save()
                result = list_sync_entry

            return result

        except ValidationError as ve:
            raise ve

        except Exception as e:
            raise ValidationError(
                f'Failed to sync listing {_id} to ListSync: {e}'
            )
