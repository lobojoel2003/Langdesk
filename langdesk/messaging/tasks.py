from celery import shared_task

from .models import Notification
from .services import MAX_ATTEMPTS, deliver


@shared_task(bind=True, max_retries=MAX_ATTEMPTS - 1, ignore_result=True)
def deliver_notification(self, notification_id: int) -> None:
    if deliver(notification_id):
        return
    attempts = (
        Notification.objects.filter(pk=notification_id).values_list("attempts", flat=True).first()
    )
    if attempts and attempts < MAX_ATTEMPTS:
        raise self.retry(countdown=60 * attempts)
