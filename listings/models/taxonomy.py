from mongoengine import Document
from mongoengine.fields import BooleanField, IntField, StringField


class TaxonomyOverride(Document):
    '''Admin overlay on the code-owned listing taxonomy.'''

    key = StringField(required=True, unique=True)
    kind = StringField(required=True, choices=('category', 'subcategory'))
    parent_key = StringField(default='')
    label = StringField()
    icon = StringField()
    is_active = BooleanField(default=True)
    sort_order = IntField()

    meta = {
        'collection': 'taxonomy_overrides',
        'indexes': [
            {'fields': ['key'], 'unique': True},
            {'fields': ['kind', 'parent_key']},
        ],
    }
