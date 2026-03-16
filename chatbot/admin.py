from django.contrib import admin
from .models import (
    User,
    ChatHistory,
    KnowledgeBase,
    AdPackage,
    Business,
    ImpressionsLog,
    Lead,
    ContactTracking,
)

admin.site.register(User)
admin.site.register(ChatHistory)
admin.site.register(KnowledgeBase)
admin.site.register(AdPackage)
admin.site.register(Business)
admin.site.register(ImpressionsLog)
admin.site.register(Lead)
admin.site.register(ContactTracking)
