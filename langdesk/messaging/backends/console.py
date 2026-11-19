import logging
import uuid

from .base import BaseSMSBackend

logger = logging.getLogger("langdesk.sms")


class ConsoleSMSBackend(BaseSMSBackend):
    """Writes texts to the log. The default, so nothing leaves the server by accident."""

    name = "console"

    def send(self, to: str, body: str) -> str:
        logger.info("SMS to %s: %s", to, body)
        return f"console-{uuid.uuid4().hex[:12]}"
