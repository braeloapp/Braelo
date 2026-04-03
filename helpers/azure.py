from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from azure.storage.blob import BlobServiceClient


class _LazyBlobServiceClient:
    """
    Defer building the Azure client until first use so Django can load settings
    (and load_dotenv) before the connection string is read.
    """

    __slots__ = ("_client",)

    def __init__(self):
        self._client = None

    def _ensure(self) -> BlobServiceClient:
        if self._client is None:
            cs = (getattr(settings, "AZURE_STORAGE_CONNECTION_STRING", None) or "").strip()
            if not cs:
                raise ImproperlyConfigured(
                    "Azure Blob Storage is not configured. Set AZURE_STORAGE_CONNECTION_STRING "
                    "or both AZURE_ACCOUNT_NAME and AZURE_ACCOUNT_KEY in the environment."
                )
            self._client = BlobServiceClient.from_connection_string(cs)
        return self._client

    def __getattr__(self, name):
        return getattr(self._ensure(), name)


blob_service_client = _LazyBlobServiceClient()
