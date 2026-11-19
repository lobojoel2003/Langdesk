import datetime as dt
from io import StringIO

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from langdesk.reports.services import (
    Period,
    _duration,
    build,
    nice_axis,
    period_from,
    request_log_csv,
    summary_csv,
)
from langdesk.scheduling.models import InterpreterRequest, Modality

pytestmark = pytest.mark.django_db
Outcome = InterpreterRequest.Outcome
Status = InterpreterRequest.Status


@pytest.fixture
def year_of_requests(make_interpreter, make_request):
    ana = make_interpreter("Ana", languages=[("es", "certified")])
    duc = make_interpreter("Duc", languages=[("vi", "qualified")], employment="contractor")
    from langdesk.roster.models import Language

    vietnamese = Language.objects.get(code="vi")
    year = timezone.localdate().year
    when = timezone.make_aware(dt.datetime(year, 3, 10, 10))

    def closed(outcome, *, interpreter=None, language=None, **fields):
        req = make_request(
            starts_at=when,
            status=Status.CANCELLED if outcome == Outcome.CANCELLED else Status.CLOSED,
            outcome=outcome,
            interpreter=interpreter,
            assigned_at=when - dt.timedelta(hours=1) if interpreter else None,
            **({"language": language} if language else {}),
            **fields,
        )
        InterpreterRequest.objects.filter(pk=req.pk).update(created_at=when - dt.timedelta(hours=2))
        return req

    closed(Outcome.COMPLETED, interpreter=ana, actual_minutes=45)
    closed(Outcome.COMPLETED, interpreter=duc, language=vietnamese, modality=Modality.VIDEO)
    closed(Outcome.VENDOR_LINE, modality=Modality.PHONE)
    closed(Outcome.UNFILLED)
    closed(Outcome.CLIENT_NO_SHOW, interpreter=ana)
    closed(Outcome.CANCELLED)
    closed(Outcome.CLIENT_DECLINED)
    make_request(starts_at=when, status=Status.ASSIGNED, interpreter=ana, fell_back_to_video=True)
    make_request(starts_in=dt.timedelta(days=400))  # outside the year
    return year


def test_build_report(year_of_requests):
    r = build(Period.year(year_of_requests))
    assert r["total"] == 8
    assert r["needed"] == 4
    assert r["served"] == 3
    assert r["fill_rate"] == 75.0
    assert r["certified_rate"] == 50.0
    assert r["unfilled"] == 1
    assert r["awaiting"] == 1
    assert r["fallbacks"] == 1
    assert r["hours"] == round((45 + 60 + 60) / 60, 1)
    assert r["median_fill_minutes"] == 60
    assert r["median_lead"] == ("2", "h")
    spanish = next(e for e in r["languages"] if e["language"] == "Spanish")
    assert (spanish["requests"], spanish["served"], spanish["unfilled"]) == (7, 2, 1)
    assert spanish["percent"] == 100
    assert {b.label for b in r["outcomes"]} >= {"Interpreted", "Outside line", "Awaiting outcome"}
    assert r["months"][2]["value"] == 8 and r["months"][2]["is_peak"]
    assert [t["value"] for t in r["month_ticks"]] == [0, 2, 4, 6, 8]
    assert {b.label: b.value for b in r["employment_hours"]} == {"Staff": 1, "Contractor": 1}


def test_empty_period():
    r = build(Period.year(2001))
    assert r["total"] == 0
    assert r["fill_rate"] is None
    assert r["median_lead"] is None
    assert r["outcomes"] == []


def test_csv_exports(year_of_requests):
    period = Period.year(year_of_requests)
    log = request_log_csv(period).splitlines()
    assert log[0].startswith("reference,language,service_type")
    assert len(log) == 9
    assert "Ana" in "".join(log)
    summary = summary_csv(build(period))
    assert "Fill rate (%),75.0" in summary
    assert "Spanish,7,3,2,1,66.7" in summary


def test_period_parsing():
    year = timezone.localdate().year
    assert period_from({}).label == str(year)
    assert period_from({"year": "2024"}) == Period.year(2024)
    assert period_from({"year": "1900"}).label == str(year)
    assert period_from({"year": "abc"}).label == str(year)
    custom = period_from({"start": "2026-01-01", "end": "2026-06-30"})
    assert custom.label == "Jan 1, 2026 – Jun 30, 2026"
    assert len(custom.months()) == 6
    assert period_from({"start": "2026-06-30", "end": "2026-01-01"}).label == str(year)


@pytest.mark.parametrize(
    ("peak", "top", "ticks"),
    [(0, 1, [0, 1]), (3, 3, [0, 1, 2, 3]), (8, 8, [0, 2, 4, 6, 8]), (37, 40, [0, 10, 20, 30, 40])],
)
def test_nice_axis(peak, top, ticks):
    assert nice_axis(peak) == (top, ticks)


def test_duration_units():
    assert _duration(0.5) == ("30", "min")
    assert _duration(5.0) == ("5", "h")
    assert _duration(75) == ("3.1", "days")


def test_report_pages(coordinator_client, year_of_requests):
    page = coordinator_client.get(reverse("reports:report"), {"year": year_of_requests})
    assert page.status_code == 200
    body = page.content.decode()
    assert "Language access report" in body
    assert "75.0" in body
    assert "still needs an outcome" in body
    csv_response = coordinator_client.get(
        reverse("reports:summary_csv"), {"year": year_of_requests}
    )
    assert csv_response["Content-Type"] == "text/csv; charset=utf-8"
    log = coordinator_client.get(reverse("reports:log_csv"), {"year": year_of_requests})
    assert log.content.decode().count("\n") == 9


def test_reports_are_for_coordinators(requester_client):
    assert requester_client.get(reverse("reports:report")).status_code == 302


def test_report_command(year_of_requests, tmp_path):
    out = StringIO()
    call_command("language_access_report", year=year_of_requests, stdout=out)
    assert "Language access report" in out.getvalue()
    target = tmp_path / "log.csv"
    call_command(
        "language_access_report", year=year_of_requests, log=True, output=str(target), stdout=out
    )
    assert target.read_text().startswith("reference,")
    with pytest.raises(Exception, match="out of range"):
        call_command("language_access_report", year=1500)
