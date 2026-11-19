import requests
from django.conf import settings

from .base import BaseSMSBackend, SMSError


class WebhookSMSBackend(BaseSMSBackend):
    """POSTs ``{"to": ..., "body": ...}`` as JSON to ``LANGDESK_SMS_WEBHOOK_URL``.

    Use it to bridge to any provider (Vonage, Plivo, an on-prem gateway) through a small
    relay. ``LANGDESK_SMS_WEBHOOK_TOKEN`` is sent as a bearer token.
    """

    name = "webhook"
    timeout = 15

    def send(self, to: str, body: str) -> str:
        url = settings.LANGDESK_SMS_WEBHOOK_URL
        if not url:
            raise SMSError("Set LANGDESK_SMS_WEBHOOK_URL to use the webhook SMS backend")
        headers = {"User-Agent": "Langdesk"}
        if settings.LANGDESK_SMS_WEBHOOK_TOKEN:
            headers["Authorization"] = f"Bearer {settings.LANGDESK_SMS_WEBHOOK_TOKEN}"
        try:
            response = requests.post(
                url, json={"to": to, "body": body}, headers=headers, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise SMSError(f"SMS webhook failed: {exc}") from exc
        if response.status_code >= 400:
            raise SMSError(f"SMS webhook returned {response.status_code}: {response.text[:200]}")
        try:
            return str(response.json().get("id", ""))
        except ValueError:
            return ""
