from django.apps import AppConfig


class ChatbotConfig(AppConfig):
    """
    Chatbot app.

    Browser geolocation: POST /chatbot/api/chat may include ``latitude`` and ``longitude``.
    ``views.api_chat`` merges reverse-geocoded ``city`` / ``state`` / ``county`` / ``zip_code``
    when those fields are missing: Google Geocoding API first if ``GOOGLE_PLACES_API_KEY`` is set
    (Geocoding API enabled), else OpenStreetMap Nominatim, so local answers follow the device area
    even when the user does not type a place in the message.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "chatbot"
