"""
monitor/api_auth.py

Lightweight API key authentication for Django function-based views.
Does not depend on DRF — works with plain HttpRequest objects.
"""
from monitor.models import APIKey


def authenticate_api_key(request):
    """
    Validate the X-API-Key header on *request*.

    Returns:
        (APIKey instance, None)    — on success
        (None, error message str)  — on failure
    """
    raw_key = request.headers.get("X-Api-Key") or request.META.get("HTTP_X_API_KEY")
    if not raw_key:
        return None, "Missing X-API-Key header"

    api_key = APIKey.authenticate(raw_key)
    if api_key is None:
        return None, "Invalid or expired API key"

    return api_key, None
