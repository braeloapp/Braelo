from django.apps import AppConfig

# AdminPanelConfig is the configuration for the admin panel app
class AdminPanelConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "admin_panel"


