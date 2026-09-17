'''
Platform-wide operational settings controlled from Admin (no code deploy).
'''

from django.db import models


class PlatformSettings(models.Model):
    '''Singleton row (pk=1) for Braelo platform rules.'''

    max_active_listings_non_business = models.PositiveIntegerField(default=10)
    search_min_chars = models.PositiveIntegerField(default=3)
    default_explore_radius_km = models.PositiveIntegerField(default=10)
    min_ios_version = models.CharField(max_length=32, blank=True, default='')
    min_android_version = models.CharField(max_length=32, blank=True, default='')
    force_update = models.BooleanField(default=False)
    phone_auth_enabled = models.BooleanField(default=True)
    google_auth_enabled = models.BooleanField(default=True)
    apple_auth_enabled = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'Platform settings'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return 'PlatformSettings'
