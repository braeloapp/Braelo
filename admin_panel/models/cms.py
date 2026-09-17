'''Publishable legal / CMS documents for the admin panel.'''

from django.conf import settings
from django.db import models


class LegalDocument(models.Model):
    DOC_PRIVACY = 'privacy'
    DOC_TERMS = 'terms'
    DOC_FAQ = 'faq'
    DOC_CHOICES = (
        (DOC_PRIVACY, 'Privacy Policy'),
        (DOC_TERMS, 'Terms of Service'),
        (DOC_FAQ, 'FAQ'),
    )

    doc_type = models.CharField(max_length=32, choices=DOC_CHOICES, unique=True)
    title = models.CharField(max_length=255, blank=True, default='')
    body = models.TextField(blank=True, default='')
    published = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='legal_document_edits',
    )

    class Meta:
        ordering = ['doc_type']

    def __str__(self):
        return f'{self.doc_type} (published={self.published})'

    @classmethod
    def get_or_create_doc(cls, doc_type):
        obj, _ = cls.objects.get_or_create(
            doc_type=doc_type,
            defaults={
                'title': dict(cls.DOC_CHOICES).get(doc_type, doc_type),
                'body': '',
                'published': False,
            },
        )
        return obj
