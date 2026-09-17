'''Admin CMS for privacy / terms / FAQ.'''

from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.views import APIView
from rest_framework import status

from helpers import handle_exceptions, response
from admin_panel.models.cms import LegalDocument
from admin_panel.services.audit import record_admin_action


ALLOWED_TYPES = {
    LegalDocument.DOC_PRIVACY,
    LegalDocument.DOC_TERMS,
    LegalDocument.DOC_FAQ,
}


def _serialize(doc):
    return {
        'doc_type': doc.doc_type,
        'title': doc.title,
        'body': doc.body,
        'published': bool(doc.published),
        'updated_at': doc.updated_at.isoformat() if doc.updated_at else None,
        'updated_by': getattr(doc.updated_by, 'email', None),
    }


class LegalDocumentAdmin(APIView):
    permission_classes = [IsAdminUser]

    @handle_exceptions
    def get(self, request, doc_type='privacy'):
        doc_type = (doc_type or 'privacy').strip().lower()
        if doc_type not in ALLOWED_TYPES:
            return response(
                status=status.HTTP_400_BAD_REQUEST,
                message='Invalid document type',
                data={},
            )
        doc = LegalDocument.get_or_create_doc(doc_type)
        return response(
            status=status.HTTP_200_OK,
            message='Document fetched',
            data=_serialize(doc),
        )

    @handle_exceptions
    def put(self, request, doc_type='privacy'):
        return self._upsert(request, doc_type)

    @handle_exceptions
    def post(self, request, doc_type='privacy'):
        return self._upsert(request, doc_type)

    def _upsert(self, request, doc_type):
        doc_type = (doc_type or 'privacy').strip().lower()
        if doc_type not in ALLOWED_TYPES:
            return response(
                status=status.HTTP_400_BAD_REQUEST,
                message='Invalid document type',
                data={},
            )
        doc = LegalDocument.get_or_create_doc(doc_type)
        previous = _serialize(doc)
        data = request.data or {}
        if 'title' in data:
            doc.title = str(data.get('title') or '')[:255]
        if 'body' in data:
            doc.body = str(data.get('body') or '')
        if 'published' in data:
            raw = data.get('published')
            if isinstance(raw, bool):
                doc.published = raw
            elif str(raw).strip().lower() in ('1', 'true', 'yes'):
                doc.published = True
            elif str(raw).strip().lower() in ('0', 'false', 'no'):
                doc.published = False
        doc.updated_by = request.user
        doc.save()
        record_admin_action(
            actor=request.user,
            action='settings',
            target_type='legal_document',
            target_id=doc_type,
            summary=f'Updated {doc_type} CMS document',
            previous_state=previous,
            new_state=_serialize(doc),
        )
        return response(
            status=status.HTTP_200_OK,
            message='Document saved',
            data=_serialize(doc),
        )


class LegalDocumentPublic(APIView):
    '''Public read of published legal copy for Flutter / web.'''

    permission_classes = [AllowAny]

    @handle_exceptions
    def get(self, request, doc_type='privacy'):
        doc_type = (doc_type or 'privacy').strip().lower()
        if doc_type not in ALLOWED_TYPES:
            return response(
                status=status.HTTP_400_BAD_REQUEST,
                message='Invalid document type',
                data={},
            )
        doc = LegalDocument.objects.filter(doc_type=doc_type, published=True).first()
        if not doc:
            return response(
                status=status.HTTP_404_NOT_FOUND,
                message='Document not published',
                data={},
            )
        return response(
            status=status.HTTP_200_OK,
            message='Document fetched',
            data={
                'doc_type': doc.doc_type,
                'title': doc.title,
                'body': doc.body,
                'updated_at': doc.updated_at.isoformat() if doc.updated_at else None,
            },
        )
