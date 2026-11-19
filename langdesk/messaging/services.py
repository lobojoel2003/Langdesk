"""Queue and deliver outbound messages.

Every message is written to :class:`Notification` first, then delivered by a Celery task
once the surrounding transaction commits (or straight away when tasks run eagerly).
A ``dedupe_key`` makes sends idempotent, which is what keeps reminders from repeating.
"""

from __future__ import annotations

import logging
import re
from email.mime.text import MIMEText

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import IntegrityError, transaction
from django.utils import timezone

from .backends import get_sms_backend
from .models import Channel, Notification

logger = logging.getLogger(__name__)

_WS = re.compile(r"\s+")
_BLANKS = re.compile(r"\n{3,}")
MAX_ATTEMPTS = 3


def clean_sms(text: str) -> str:
    return _WS.sub(" ", text).strip()


def clean_email(text: str) -> str:
    lines = [line.rstrip() for line in text.strip().splitlines()]
    return _BLANKS.sub("\n\n", "\n".join(lines)) + "\n"


def _create(dedupe_key: str | None, **fields) -> Notification | None:
    if dedupe_key and Notification.objects.filter(dedupe_key=dedupe_key).exists():
        return None
    try:
        with transaction.atomic():
            return Notification.objects.create(dedupe_key=dedupe_key, **fields)
    except IntegrityError:
        return None


def queue_sms(to: str, body: str, *, kind: str, dedupe_key: str | None = None, **links):
    notification = _create(
        dedupe_key, channel=Channel.SMS, kind=kind, to_address=to, body=clean_sms(body), **links
    )
    if notification:
        enqueue(notification)
    return notification


def queue_email(
    to: str,
    subject: str,
    body: str,
    *,
    kind: str,
    ics: str = "",
    dedupe_key: str | None = None,
    **links,
):
    notification = _create(
        dedupe_key,
        channel=Channel.EMAIL,
        kind=kind,
        to_address=to,
        subject=subject[:200],
        body=clean_email(body),
        ics=ics,
        **links,
    )
    if notification:
        enqueue(notification)
    return notification


def enqueue(notification: Notification) -> None:
    if settings.LANGDESK_TASKS_EAGER:
        deliver(notification.pk)
        return
    from .tasks import deliver_notification

    pk = notification.pk
    transaction.on_commit(lambda: deliver_notification.delay(pk))


def deliver(pk: int) -> bool:
    """Send notification ``pk``. Returns True when it is (or already was) sent."""
    with transaction.atomic():
        notification = Notification.objects.select_for_update().filter(pk=pk).first()
        if notification is None:
            return False
        if notification.status == Notification.Status.SENT:
            return True
        notification.attempts += 1
        try:
            if notification.channel == Channel.SMS:
                notification.provider_id = get_sms_backend().send(
                    notification.to_address, notification.body
                )
            else:
                _send_email(notification)
        except Exception as exc:
            logger.warning("Delivery of notification %s failed: %s", pk, exc)
            notification.status = Notification.Status.FAILED
            notification.error = str(exc)[:2000]
            notification.save(update_fields=["status", "error", "attempts"])
            return False
        notification.status = Notification.Status.SENT
        notification.sent_at = timezone.now()
        notification.error = ""
        notification.save(update_fields=["status", "sent_at", "error", "attempts", "provider_id"])
        return True


def _send_email(notification: Notification) -> None:
    message = EmailMessage(
        subject=notification.subject,
        body=notification.body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[notification.to_address],
    )
    if notification.ics:
        method = "CANCEL" if "METHOD:CANCEL" in notification.ics else "REQUEST"
        part = MIMEText(notification.ics, "calendar", "utf-8")
        part.set_param("method", method)
        part.add_header("Content-Disposition", "attachment", filename="invite.ics")
        message.attach(part)
    message.send(fail_silently=False)
