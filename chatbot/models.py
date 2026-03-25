"""
Django ORM models for Braelo chatbot: User, ChatHistory, KnowledgeBase, AdPackage, Business, ImpressionsLog, Lead, ContactTracking.
Table names prefixed with chatbot_ to avoid conflict with braelo users app.
"""
from django.db import models
from django.utils import timezone


class User(models.Model):
    """Chat user; account required for history and location-based analysis."""
    external_id = models.CharField(max_length=128, unique=True, db_index=True)
    display_name = models.CharField(max_length=128, null=True, blank=True)
    email = models.EmailField(max_length=254, null=True, blank=True)
    phone = models.CharField(max_length=32, null=True, blank=True)
    language_preference = models.CharField(max_length=8, default="en")
    state = models.CharField(max_length=64, null=True, blank=True)
    city = models.CharField(max_length=128, null=True, blank=True)
    zip_code = models.CharField(max_length=16, null=True, blank=True, db_index=True)
    county = models.CharField(max_length=128, null=True, blank=True, db_index=True)
    location_enabled = models.BooleanField(default=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    is_banned = models.BooleanField(default=False)

    class Meta:
        db_table = "chatbot_users"

    def __str__(self):
        return self.external_id

    @property
    def has_complete_location(self):
        return bool(self.state and self.county and self.zip_code)

    @property
    def has_contact_details(self):
        return bool(self.email and self.phone)


class ChatHistory(models.Model):
    """Stores every user ↔ assistant message."""
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    external_id = models.CharField(max_length=128, null=True, blank=True, db_index=True)
    role = models.CharField(max_length=16)  # user | assistant
    content = models.TextField()
    intent = models.CharField(max_length=64, null=True, blank=True)
    entities_json = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "chatbot_chat_history"

    def __str__(self):
        return f"{self.role}: {self.content[:50]}"


class KnowledgeBase(models.Model):
    """Q&A knowledge base loaded from DOCX files (by state/county), with optional OpenAI embeddings."""
    state = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    county = models.CharField(max_length=128, null=True, blank=True, db_index=True)
    question = models.TextField()
    answer = models.TextField()
    embedding_json = models.TextField(null=True, blank=True)  # JSON array of floats
    # Normalized tokens from Q+A for hybrid retrieval (mirrors Mongo knowledge_base.search_tokens)
    search_tokens = models.JSONField(null=True, blank=True)
    document_source = models.CharField(max_length=256, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "chatbot_knowledge_base"

    def __str__(self):
        return self.question[:80]


class AdPackage(models.Model):
    """Ad packages that businesses can subscribe to for priority placement."""
    name = models.CharField(max_length=64)
    priority = models.IntegerField(default=0)  # higher = shown first
    max_impressions = models.IntegerField(default=1000)

    class Meta:
        db_table = "chatbot_ad_packages"

    def __str__(self):
        return self.name


class Business(models.Model):
    """Local businesses; service categories are main anchor; may have WhatsApp URL for contact."""
    name = models.CharField(max_length=256)
    category = models.CharField(max_length=128, null=True, blank=True, db_index=True)
    subcategory = models.CharField(max_length=128, null=True, blank=True)
    state = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    city = models.CharField(max_length=128, null=True, blank=True)
    zip_code = models.CharField(max_length=16, null=True, blank=True, db_index=True)
    county = models.CharField(max_length=128, null=True, blank=True, db_index=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    languages = models.CharField(max_length=256, null=True, blank=True)  # comma-separated: en,es,pt
    contact_info = models.TextField(null=True, blank=True)
    whatsapp_url = models.URLField(max_length=512, null=True, blank=True)
    ad_package = models.ForeignKey(AdPackage, on_delete=models.SET_NULL, null=True, blank=True)
    impression_cap = models.IntegerField(default=1000)
    impressions_used = models.IntegerField(default=0)
    rotation_index = models.IntegerField(default=0)  # for fair visibility across eligible businesses
    created_at = models.DateTimeField(default=timezone.now)
    is_active = models.BooleanField(default=True)
    is_banned = models.BooleanField(default=False)

    class Meta:
        db_table = "chatbot_businesses"

    def __str__(self):
        return self.name


class ImpressionsLog(models.Model):
    """Log of every time a business is shown to a user."""
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    external_id = models.CharField(max_length=128, null=True, blank=True)
    session_id = models.CharField(max_length=128, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "chatbot_impressions_log"


class Lead(models.Model):
    """Tracks user actions (clicks) on businesses."""
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    external_id = models.CharField(max_length=128, null=True, blank=True)
    action_type = models.CharField(max_length=32, default="click")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "chatbot_leads"


class ContactTracking(models.Model):
    """Tracks contact intentions (WhatsApp, phone, email) for analytics; no monetization per contact."""
    CONTACT_TYPES = (("whatsapp", "WhatsApp"), ("phone", "Phone"), ("email", "Email"))
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    external_id = models.CharField(max_length=128, null=True, blank=True)
    contact_type = models.CharField(max_length=32, choices=CONTACT_TYPES, default="whatsapp")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "chatbot_contact_tracking"
