from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from langdesk.reports.services import Period, build, request_log_csv, summary_csv


class Command(BaseCommand):
    help = "Write the language-access report (or the full request log) as CSV."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--year", type=int, default=timezone.localdate().year)
        parser.add_argument("--log", action="store_true", help="Write one row per request.")
        parser.add_argument("-o", "--output", help="File to write. Defaults to stdout.")

    def handle(self, *args, year: int, log: bool, output: str | None, **options) -> None:
        if not 2000 <= year <= 2100:
            raise CommandError("Year out of range.")
        period = Period.year(year)
        content = request_log_csv(period) if log else summary_csv(build(period))
        if output:
            Path(output).write_text(content, encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Wrote {output}"))
        else:
            self.stdout.write(content, ending="")
