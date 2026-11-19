import requests
from django.conf import settings

from .base import BaseSMSBackend, SMSError

API = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"


class TwilioSMSBackend(BaseSMSBackend):
    """Sends through Twilio's REST API. Needs ``TWILIO_ACCOUNT_SID`` and ``TWILIO_AUTH_TOKEN``,
    plus ``TWILIO_FROM_NUMBER`` or ``TWILIO_MESSAGING_SERVICE_SID``."""

    name = "twilio"
    timeout = 15

    def send(self, to: str, body: str) -> str:
        sid, token = settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN
        if not sid or not token:
            raise SMSError("Twilio is not configured: set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN")
        data = {"To": to, "Body": body}
        if settings.TWILIO_MESSAGING_SERVICE_SID:
            data["MessagingServiceSid"] = settings.TWILIO_MESSAGING_SERVICE_SID
        elif settings.TWILIO_FROM_NUMBER:
            data["From"] = settings.TWILIO_FROM_NUMBER
        else:
            raise SMSError("Set TWILIO_FROM_NUMBER or TWILIO_MESSAGING_SERVICE_SID")
        try:
            response = requests.post(
                API.format(sid=sid), data=data, auth=(sid, token), timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise SMSError(f"Twilio request failed: {exc}") from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("message", response.text)
            except ValueError:
                detail = response.text
            raise SMSError(f"Twilio error {response.status_code}: {detail}")
        return response.json().get("sid", "")
