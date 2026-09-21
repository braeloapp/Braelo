from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAdminUser
from rest_framework.views import APIView

from helpers import handle_exceptions, response
from listings.models.taxonomy import TaxonomyOverride
from listings.services.taxonomy import (
    build_taxonomy_catalog,
    clear_taxonomy_display_cache,
    create_taxonomy_entry,
    delete_taxonomy_entry,
    override_lookup_key,
    resolve_taxonomy_target_or_admin,
)


class AdminTaxonomy(APIView):
    '''Full admin CRUD for platform + custom taxonomy overlays.'''

    permission_classes = [IsAdminUser]

    def get(self, request):
        overrides = list(TaxonomyOverride.objects.all())
        return response(
            status=status.HTTP_200_OK,
            message='Taxonomy fetched successfully',
            data={'categories': build_taxonomy_catalog(overrides)},
        )

    def post(self, request):
        '''Create or upsert a taxonomy overlay (category or subcategory).'''
        try:
            result = create_taxonomy_entry(request.data or {})
        except ValueError as exc:
            raise ValidationError({'detail': str(exc)}) from exc
        clear_taxonomy_display_cache()
        overrides = list(TaxonomyOverride.objects.all())
        return response(
            status=status.HTTP_201_CREATED,
            message='Taxonomy entry saved',
            data={
                'entry': result,
                'categories': build_taxonomy_catalog(overrides),
            },
        )

    def put(self, request):
        return self.patch(request)

    @handle_exceptions
    def patch(self, request):
        kind = (request.data.get('kind') or 'category').strip()
        key = (request.data.get('key') or '').strip()
        parent_key = (request.data.get('parent_key') or '').strip()
        if not key:
            raise ValidationError({'key': 'key is required'})
        try:
            parent, sub = resolve_taxonomy_target_or_admin(kind, key, parent_key)
        except ValueError as exc:
            raise ValidationError({'key': str(exc)}) from exc

        canonical_key = sub if kind == 'subcategory' else parent
        parent_key = parent if kind == 'subcategory' else ''
        lookup = override_lookup_key(kind, canonical_key, parent_key)
        row = TaxonomyOverride.objects(key=lookup).first()
        if row is None:
            row = TaxonomyOverride(
                key=lookup,
                kind=kind,
                parent_key=parent_key,
            )
        if 'label' in request.data:
            label = (request.data.get('label') or '').strip()
            if not label:
                raise ValidationError({'label': 'label cannot be empty'})
            row.label = label
        if 'is_active' in request.data:
            row.is_active = bool(request.data.get('is_active'))
        if 'sort_order' in request.data and request.data.get('sort_order') is not None:
            try:
                row.sort_order = int(request.data.get('sort_order'))
            except (TypeError, ValueError) as exc:
                raise ValidationError(
                    {'sort_order': 'sort_order must be an integer'}
                ) from exc
        if 'icon' in request.data:
            row.icon = request.data.get('icon') or ''
        row.is_removed = False
        row.save()
        clear_taxonomy_display_cache()
        overrides = list(TaxonomyOverride.objects.all())
        return response(
            status=status.HTTP_200_OK,
            message='Taxonomy updated',
            data={'categories': build_taxonomy_catalog(overrides)},
        )

    @handle_exceptions
    def delete(self, request):
        kind = (request.data.get('kind') or 'category').strip()
        key = (request.data.get('key') or '').strip()
        parent_key = (request.data.get('parent_key') or '').strip()
        try:
            result = delete_taxonomy_entry(
                kind=kind, key=key, parent_key=parent_key
            )
        except ValueError as exc:
            raise ValidationError({'detail': str(exc)}) from exc
        clear_taxonomy_display_cache()
        overrides = list(TaxonomyOverride.objects.all())
        return response(
            status=status.HTTP_200_OK,
            message='Taxonomy entry removed',
            data={
                'entry': result,
                'categories': build_taxonomy_catalog(overrides),
            },
        )
