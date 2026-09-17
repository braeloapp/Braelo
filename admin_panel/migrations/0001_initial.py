# Generated manually for Admin Control Center foundation

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AdminAuditLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('actor_email', models.EmailField(blank=True, default='', max_length=254)),
                ('action', models.CharField(choices=[('create', 'Create'), ('update', 'Update'), ('delete', 'Delete'), ('activate', 'Activate'), ('deactivate', 'Deactivate'), ('warn', 'Warn'), ('ban', 'Ban'), ('ignore', 'Ignore'), ('resolve', 'Resolve'), ('reply', 'Reply'), ('notify', 'Notify'), ('settings', 'Settings'), ('other', 'Other')], db_index=True, max_length=32)),
                ('target_type', models.CharField(db_index=True, max_length=64)),
                ('target_id', models.CharField(blank=True, db_index=True, default='', max_length=64)),
                ('summary', models.CharField(max_length=255)),
                ('reason', models.TextField(blank=True, default='')),
                ('previous_state', models.JSONField(blank=True, default=dict)),
                ('new_state', models.JSONField(blank=True, default=dict)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='admin_audit_actions', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='PlatformSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('max_active_listings_non_business', models.PositiveIntegerField(default=10)),
                ('search_min_chars', models.PositiveIntegerField(default=3)),
                ('default_explore_radius_km', models.PositiveIntegerField(default=10)),
                ('min_ios_version', models.CharField(blank=True, default='', max_length=32)),
                ('min_android_version', models.CharField(blank=True, default='', max_length=32)),
                ('force_update', models.BooleanField(default=False)),
                ('phone_auth_enabled', models.BooleanField(default=True)),
                ('google_auth_enabled', models.BooleanField(default=True)),
                ('apple_auth_enabled', models.BooleanField(default=False)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name_plural': 'Platform settings',
            },
        ),
        migrations.AddIndex(
            model_name='adminauditlog',
            index=models.Index(fields=['target_type', 'target_id', '-created_at'], name='admin_panel_target__7c2a1d_idx'),
        ),
        migrations.AddIndex(
            model_name='adminauditlog',
            index=models.Index(fields=['action', '-created_at'], name='admin_panel_action_8f4e2b_idx'),
        ),
    ]
