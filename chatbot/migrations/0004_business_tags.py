# Generated manually for Lista business directory search

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chatbot", "0003_knowledgebase_search_tokens"),
    ]

    operations = [
        migrations.AddField(
            model_name="business",
            name="tags",
            field=models.TextField(blank=True, null=True),
        ),
    ]
