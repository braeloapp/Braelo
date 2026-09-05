'''Central email send + template rendering. Views must not call SMTP directly.'''

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger('notifications.email')

BRAND_NAME = 'Braelo'
BRAND_COLOR = '#CD9403'


@dataclass(frozen=True)
class EmailTemplate:
    key: str
    subject: str
    html: str
    text: str


class EmailTemplateService:
    TEMPLATES = {
        'verify_email': EmailTemplate(
            key='verify_email',
            subject='Verify your Braelo email',
            html='email/verify_email.html',
            text='email/verify_email.txt',
        ),
        'welcome': EmailTemplate(
            key='welcome',
            subject='Welcome to Braelo',
            html='email/welcome.html',
            text='email/welcome.txt',
        ),
        'password_reset': EmailTemplate(
            key='password_reset',
            subject='Your Braelo password reset code',
            html='email/password_reset.html',
            text='email/password_reset.txt',
        ),
        'password_changed': EmailTemplate(
            key='password_changed',
            subject='Your Braelo password was changed',
            html='email/password_changed.html',
            text='email/password_changed.txt',
        ),
        'security_alert': EmailTemplate(
            key='security_alert',
            subject='Security alert on your Braelo account',
            html='email/security_alert.html',
            text='email/security_alert.txt',
        ),
        'listing_created': EmailTemplate(
            key='listing_created',
            subject='Your Braelo listing is live',
            html='email/listing_created.html',
            text='email/listing_created.txt',
        ),
        'business_activated': EmailTemplate(
            key='business_activated',
            subject='Your Braelo business profile is ready',
            html='email/business_activated.html',
            text='email/business_activated.txt',
        ),
        'support_reply': EmailTemplate(
            key='support_reply',
            subject='Support replied to your Braelo request',
            html='email/support_reply.html',
            text='email/support_reply.txt',
        ),
    }

    def get(self, template_key: str) -> EmailTemplate:
        template = self.TEMPLATES.get(template_key)
        if template is None:
            raise ValueError(f'Unknown email template: {template_key}')
        return template

    def render(self, template_key: str, context: dict | None = None):
        template = self.get(template_key)
        payload = {
            'brand_name': BRAND_NAME,
            'brand_color': BRAND_COLOR,
            'support_email': getattr(settings, 'DEFAULT_FROM_EMAIL', ''),
            **(context or {}),
        }
        html = render_to_string(template.html, payload)
        text = render_to_string(template.text, payload)
        subject = payload.get('subject') or template.subject
        return subject, html, text


class EmailService:
    def __init__(self, templates: EmailTemplateService | None = None):
        self.templates = templates or EmailTemplateService()

    def send(
        self,
        *,
        to,
        template_key: str,
        context: dict | None = None,
        fail_silently: bool = False,
    ) -> bool:
        recipients = [addr for addr in _as_recipients(to) if addr]
        if not recipients:
            if fail_silently:
                return False
            raise ValueError('Email recipient is required.')

        subject, html, text = self.templates.render(template_key, context)
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None) or None
        message = EmailMultiAlternatives(
            subject=subject,
            body=text,
            from_email=from_email,
            to=recipients,
        )
        message.attach_alternative(html, 'text/html')
        try:
            message.send(fail_silently=False)
            return True
        except Exception:
            logger.exception(
                'Failed to send email template=%s to=%s',
                template_key,
                recipients,
            )
            if fail_silently:
                return False
            raise

    def send_best_effort(self, *, to, template_key: str, context: dict | None = None) -> bool:
        return self.send(
            to=to,
            template_key=template_key,
            context=context,
            fail_silently=True,
        )


def _as_recipients(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


email_service = EmailService()
email_templates = EmailTemplateService()
