import uuid
from dataclasses import dataclass

from .base import BaseSMSBackend


@dataclass
class SentSMS:
    to: str
    body: str
    id: str


outbox: list[SentSMS] = []


class LocMemSMSBackend(BaseSMSBackend):
    """Keeps texts in ``outbox`` for tests."""

    name = "locmem"

    def send(self, to: str, body: str) -> str:
        message = SentSMS(to=to, body=body, id=f"locmem-{uuid.uuid4().hex[:12]}")
        outbox.append(message)
        return message.id
