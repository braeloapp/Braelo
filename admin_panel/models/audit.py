'''
Immutable staff action audit trail for the Braelo Admin Control Center.
'''

from django.conf import settings
from django.db import models


class AdminAuditLog(models.Model):
    '''Who / what / when / target / before / after for admin mutations.'''

    ACTION_CHOICES = (
        ('create', 'Create'),
        ('update', 'Update'),
        ('delete', 'Delete'),
        ('activate', 'Activate'),
        ('deactivate', 'Deactivate'),
        ('warn', 'Warn'),
        ('ban', 'Ban'),
        ('ignore', 'Ignore'),
        ('resolve', 'Resolve'),
        ('reply', 'Reply'),
        ('notify', 'Notify'),
        ('settings', 'Settings'),
        ('other', 'Other'),
    )

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='admin_audit_actions',
    )
    actor_email = models.EmailField(blank=True, default='')
    action = models.CharField(max_length=32, choices=ACTION_CHOICES, db_index=True)
    target_type = models.CharField(max_length=64, db_index=True)
    target_id = models.CharField(max_length=64, blank=True, default='', db_index=True)
    summary = models.CharField(max_length=255)
    reason = models.TextField(blank=True, default='')
    previous_state = models.JSONField(default=dict, blank=True)
    new_state = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['target_type', 'target_id', '-created_at']),
            models.Index(fields=['action', '-created_at']),
        ]

    def __str__(self):
        return f'{self.action} {self.target_type}:{self.target_id} by {self.actor_email}'
