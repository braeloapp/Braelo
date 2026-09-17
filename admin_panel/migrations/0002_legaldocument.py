from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('admin_panel', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='LegalDocument',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('doc_type', models.CharField(choices=[('privacy', 'Privacy Policy'), ('terms', 'Terms of Service'), ('faq', 'FAQ')], max_length=32, unique=True)),
                ('title', models.CharField(blank=True, default='', max_length=255)),
                ('body', models.TextField(blank=True, default='')),
                ('published', models.BooleanField(default=False)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='legal_document_edits', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['doc_type'],
            },
        ),
    ]
