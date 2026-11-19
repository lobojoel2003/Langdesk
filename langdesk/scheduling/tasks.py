import logging

from celery import shared_task
from django.utils import timezone

from .models import InterpreterRequest, Offer
from .services import dispatch

logger = logging.getLogger(__name__)


@shared_task(ignore_result=True)
def run_dispatcher() -> dict[str, int]:
    """Expire offers, send the next wave, fall back to video and send reminders."""
    stats = dispatch.run_dispatcher()
    if any(stats.values()):
        logger.info("Dispatcher: %s", stats)
    return stats


@shared_task(ignore_result=True)
def expire_stale_offers() -> int:
    """Safety net: withdraw pending offers whose request is no longer open."""
    return (
        Offer.objects.pending()
        .exclude(request__status=InterpreterRequest.Status.OPEN)
        .update(status=Offer.Status.WITHDRAWN)
    ) + Offer.objects.pending().filter(request__ends_at__lte=timezone.now()).update(
        status=Offer.Status.EXPIRED
    )
