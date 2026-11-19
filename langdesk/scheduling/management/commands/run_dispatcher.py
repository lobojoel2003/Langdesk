import time

from django.core.management.base import BaseCommand

from langdesk.scheduling.services.dispatch import run_dispatcher


class Command(BaseCommand):
    help = (
        "Run the dispatcher once (expire offers, next wave, video fallback, reminders). "
        "Use --loop to keep running without Celery beat, or call it from cron."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--loop", action="store_true", help="Run every --interval seconds.")
        parser.add_argument("--interval", type=int, default=60)

    def handle(self, *args, loop: bool, interval: int, **options) -> None:
        while True:
            stats = run_dispatcher()
            self.stdout.write(", ".join(f"{key}={value}" for key, value in stats.items()))
            if not loop:
                return
            time.sleep(interval)
