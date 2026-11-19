from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from langdesk.core.roles import coordinator_required
from langdesk.scheduling.models import InterpreterRequest

from .services import build, period_from, request_log_csv, summary_csv


def _csv(content: str, name: str) -> HttpResponse:
    response = HttpResponse(content, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


def _slug(period) -> str:
    return f"{period.start:%Y%m%d}-{period.end:%Y%m%d}"


@coordinator_required
def report(request):
    period = period_from(request.GET)
    first = (
        InterpreterRequest.objects.order_by("starts_at").values_list("starts_at", flat=True).first()
    )
    this_year = timezone.localdate().year
    first_year = timezone.localtime(first).year if first else this_year
    years = list(range(max(this_year, first_year), min(this_year, first_year) - 1, -1))
    return render(request, "reports/report.html", {"r": build(period), "years": years})


@coordinator_required
def summary_export(request):
    period = period_from(request.GET)
    return _csv(summary_csv(build(period)), f"langdesk-report-{_slug(period)}.csv")


@coordinator_required
def log_export(request):
    period = period_from(request.GET)
    return _csv(request_log_csv(period), f"langdesk-request-log-{_slug(period)}.csv")
