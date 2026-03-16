# Generated manually for chatbot app (merge from standalone chatbot).

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="User",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("external_id", models.CharField(db_index=True, max_length=128, unique=True)),
                ("language_preference", models.CharField(default="en", max_length=8)),
                ("state", models.CharField(blank=True, max_length=64, null=True)),
                ("city", models.CharField(blank=True, max_length=128, null=True)),
                ("zip_code", models.CharField(blank=True, db_index=True, max_length=16, null=True)),
                ("county", models.CharField(blank=True, db_index=True, max_length=128, null=True)),
                ("location_enabled", models.BooleanField(default=True)),
                ("latitude", models.DecimalField(blank=True, decimal_places=7, max_digits=10, null=True)),
                ("longitude", models.DecimalField(blank=True, decimal_places=7, max_digits=10, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_banned", models.BooleanField(default=False)),
            ],
            options={"db_table": "chatbot_users"},
        ),
        migrations.CreateModel(
            name="AdPackage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=64)),
                ("priority", models.IntegerField(default=0)),
                ("max_impressions", models.IntegerField(default=1000)),
            ],
            options={"db_table": "chatbot_ad_packages"},
        ),
        migrations.CreateModel(
            name="KnowledgeBase",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("state", models.CharField(blank=True, db_index=True, max_length=64, null=True)),
                ("county", models.CharField(blank=True, db_index=True, max_length=128, null=True)),
                ("question", models.TextField()),
                ("answer", models.TextField()),
                ("embedding_json", models.TextField(blank=True, null=True)),
                ("document_source", models.CharField(blank=True, max_length=256, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={"db_table": "chatbot_knowledge_base"},
        ),
        migrations.CreateModel(
            name="Business",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=256)),
                ("category", models.CharField(blank=True, db_index=True, max_length=128, null=True)),
                ("subcategory", models.CharField(blank=True, max_length=128, null=True)),
                ("state", models.CharField(blank=True, db_index=True, max_length=64, null=True)),
                ("city", models.CharField(blank=True, max_length=128, null=True)),
                ("zip_code", models.CharField(blank=True, db_index=True, max_length=16, null=True)),
                ("county", models.CharField(blank=True, db_index=True, max_length=128, null=True)),
                ("latitude", models.DecimalField(blank=True, decimal_places=7, max_digits=10, null=True)),
                ("longitude", models.DecimalField(blank=True, decimal_places=7, max_digits=10, null=True)),
                ("languages", models.CharField(blank=True, max_length=256, null=True)),
                ("contact_info", models.TextField(blank=True, null=True)),
                ("whatsapp_url", models.URLField(blank=True, max_length=512, null=True)),
                ("impression_cap", models.IntegerField(default=1000)),
                ("impressions_used", models.IntegerField(default=0)),
                ("rotation_index", models.IntegerField(default=0)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("is_active", models.BooleanField(default=True)),
                ("is_banned", models.BooleanField(default=False)),
                ("ad_package", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="chatbot.adpackage")),
            ],
            options={"db_table": "chatbot_businesses"},
        ),
        migrations.CreateModel(
            name="ChatHistory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("external_id", models.CharField(blank=True, db_index=True, max_length=128, null=True)),
                ("role", models.CharField(max_length=16)),
                ("content", models.TextField()),
                ("intent", models.CharField(blank=True, max_length=64, null=True)),
                ("entities_json", models.TextField(blank=True, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="chatbot.user")),
            ],
            options={"db_table": "chatbot_chat_history"},
        ),
        migrations.CreateModel(
            name="ImpressionsLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("external_id", models.CharField(blank=True, max_length=128, null=True)),
                ("session_id", models.CharField(blank=True, max_length=128, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("business", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="chatbot.business")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="chatbot.user")),
            ],
            options={"db_table": "chatbot_impressions_log"},
        ),
        migrations.CreateModel(
            name="Lead",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("external_id", models.CharField(blank=True, max_length=128, null=True)),
                ("action_type", models.CharField(default="click", max_length=32)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("business", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="chatbot.business")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="chatbot.user")),
            ],
            options={"db_table": "chatbot_leads"},
        ),
        migrations.CreateModel(
            name="ContactTracking",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("external_id", models.CharField(blank=True, max_length=128, null=True)),
                ("contact_type", models.CharField(choices=[("whatsapp", "WhatsApp"), ("phone", "Phone"), ("email", "Email")], default="whatsapp", max_length=32)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("business", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="chatbot.business")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="chatbot.user")),
            ],
            options={"db_table": "chatbot_contact_tracking"},
        ),
    ]
