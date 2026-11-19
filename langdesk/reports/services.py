"""The language-access report.

Every request ends with a recorded outcome, so the yearly report is a query, not a project.
Definitions used throughout:

* **Needed an interpreter** - closed requests that were interpreted, covered by an outside
  line, went unfilled, or where the interpreter didn't show. Cancellations, client no-shows
  and documented client waivers are reported but not counted against the fill rate.
* **Fill rate** - interpreted or covered by an outside line, divided by needed.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import statistics
from collections import Counter, OrderedDict
from dataclasses import dataclass

from django.utils import timezone
from django.utils.formats import date_format

from langdesk.roster.models import InterpreterLanguage
from langdesk.scheduling.models import InterpreterRequest, Modality

Outcome = InterpreterRequest.Outcome
Status = InterpreterRequest.Status
NEEDED = {Outcome.COMPLETED, Outcome.VENDOR_LINE, Outcome.UNFILLED, Outcome.INTERPRETER_NO_SHOW}
SERVED = set(InterpreterRequest.SERVED_OUTCOMES)


@dataclass(frozen=True)
class Period:
    start: dt.date
    end: dt.date  # inclusive

    @property
    def label(self) -> str:
        if (
            self.start.month == 1
            and self.start.day == 1
            and self.end == dt.date(self.start.year, 12, 31)
        ):
            return str(self.start.year)
        return f"{date_format(self.start, 'M j, Y')} – {date_format(self.end, 'M j, Y')}"

    @property
    def bounds(self) -> tuple[dt.datetime, dt.datetime]:
        start = timezone.make_aware(dt.datetime.combine(self.start, dt.time.min))
        end = timezone.make_aware(dt.datetime.combine(self.end + dt.timedelta(days=1), dt.time.min))
        return start, end

    def months(self) -> list[dt.date]:
        months, cursor = [], self.start.replace(day=1)
        while cursor <= self.end:
            months.append(cursor)
            cursor = (cursor + dt.timedelta(days=32)).replace(day=1)
        return months

    @classmethod
    def year(cls, year: int) -> Period:
        return cls(dt.date(year, 1, 1), dt.date(year, 12, 31))


def period_from(params) -> Period:
    """Read ``?year=2026`` or ``?start=2026-01-01&end=2026-06-30``; default this year."""
    try:
        start = dt.date.fromisoformat(params.get("start", ""))
        end = dt.date.fromisoformat(params.get("end", ""))
        if start <= end:
            return Period(start, end)
    except ValueError:
        pass
    try:
        year = int(params.get("year", ""))
        if 2000 <= year <= 2100:
            return Period.year(year)
    except ValueError:
        pass
    return Period.year(timezone.localdate().year)


def _requests(period: Period):
    start, end = period.bounds
    return (
        InterpreterRequest.objects.filter(starts_at__gte=start, starts_at__lt=end)
        .select_related("language", "location", "department", "interpreter", "requested_by")
        .order_by("starts_at", "pk")
    )


def _credentials(rows) -> dict[tuple[int, int], str]:
    pairs = {(r.interpreter_id, r.language_id) for r in rows if r.interpreter_id}
    if not pairs:
        return {}
    skills = InterpreterLanguage.objects.filter(
        interpreter_id__in={i for i, _ in pairs}, language_id__in={lang for _, lang in pairs}
    )
    return {(s.interpreter_id, s.language_id): s.effective_credential for s in skills}


SHORT_OUTCOMES = {
    Outcome.COMPLETED: "Interpreted",
    Outcome.VENDOR_LINE: "Outside line",
    Outcome.CLIENT_NO_SHOW: "Client no-show",
    Outcome.CANCELLED: "Cancelled",
    Outcome.CLIENT_DECLINED: "Client declined",
    Outcome.UNFILLED: "Unfilled",
    Outcome.INTERPRETER_NO_SHOW: "Interpreter no-show",
}


def nice_axis(peak: int, target_ticks: int = 4) -> tuple[int, list[int]]:
    """A round axis maximum at or above ``peak`` and evenly spaced ticks."""
    if peak <= 0:
        return 1, [0, 1]
    raw = peak / target_ticks
    magnitude = 10 ** (len(str(int(raw))) - 1) if raw >= 1 else 1
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw)
    step = max(1, int(step))
    top = step * -(-peak // step)
    return top, list(range(0, top + 1, step))


def _duration(hours: float) -> tuple[str, str]:
    """``(value, unit)`` for a median wait: minutes, hours or days."""
    if hours < 1:
        return f"{round(hours * 60)}", "min"
    if hours < 48:
        return f"{hours:.1f}".removesuffix(".0"), "h"
    return f"{hours / 24:.1f}".removesuffix(".0"), "days"


def _rate(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


@dataclass
class Bar:
    label: str
    value: int
    detail: str = ""
    percent: float = 0.0  # width relative to the largest bar

    @property
    def fraction(self) -> float:
        return self.percent / 100


def _bars(counter: Counter, *, total: int | None = None, order: list[str] | None = None):
    items = [(key, counter[key]) for key in order] if order else counter.most_common()
    items = [(key, value) for key, value in items if value]
    peak = max((value for _, value in items), default=0)
    bars = []
    for key, value in items:
        share = f"{round(100 * value / total)}%" if total else ""
        bars.append(Bar(str(key), value, share, round(100 * value / peak, 1) if peak else 0))
    return bars


def build(period: Period) -> dict:
    rows = list(_requests(period))
    now = timezone.now()
    credentials = _credentials(rows)

    outcomes = Counter(r.outcome for r in rows if r.status in {Status.CLOSED, Status.CANCELLED})
    awaiting = sum(1 for r in rows if r.is_active and r.ends_at <= now)
    upcoming = sum(1 for r in rows if r.is_active and r.ends_at > now)
    needed = sum(outcomes[o] for o in NEEDED)
    served = sum(outcomes[o] for o in SERVED)
    completed = [r for r in rows if r.outcome == Outcome.COMPLETED]
    certified = sum(
        1
        for r in completed
        if credentials.get((r.interpreter_id, r.language_id))
        == InterpreterLanguage.Credential.CERTIFIED
    )
    minutes = sum(r.billable_minutes for r in rows if r.outcome in SERVED)
    lead_hours = [(r.starts_at - r.created_at).total_seconds() / 3600 for r in rows]
    fill_minutes = [
        (r.assigned_at - r.created_at).total_seconds() / 60
        for r in rows
        if r.assigned_at and r.assigned_at >= r.created_at
    ]

    by_language: OrderedDict[str, dict] = OrderedDict()
    for r in sorted(rows, key=lambda r: r.language.name):
        entry = by_language.setdefault(
            r.language.name,
            {
                "language": r.language.name,
                "requests": 0,
                "served": 0,
                "needed": 0,
                "unfilled": 0,
                "minutes": 0,
            },
        )
        entry["requests"] += 1
        if r.outcome in NEEDED:
            entry["needed"] += 1
        if r.outcome in SERVED:
            entry["served"] += 1
            entry["minutes"] += r.billable_minutes
        if r.outcome == Outcome.UNFILLED:
            entry["unfilled"] += 1
    languages = sorted(by_language.values(), key=lambda e: (-e["requests"], e["language"]))
    peak = max((e["requests"] for e in languages), default=0)
    for entry in languages:
        entry["fill_rate"] = _rate(entry["served"], entry["needed"])
        entry["hours"] = round(entry["minutes"] / 60, 1)
        entry["percent"] = round(100 * entry["requests"] / peak, 1) if peak else 0
        entry["fraction"] = entry["percent"] / 100

    month_counts = Counter(timezone.localtime(r.starts_at).date().replace(day=1) for r in rows)
    month_peak = max(month_counts.values(), default=0)
    axis_max, ticks = nice_axis(month_peak)
    months = [
        {
            "label": date_format(month, "M"),
            "long": date_format(month, "F Y"),
            "value": month_counts[month],
            "percent": round(100 * month_counts[month] / axis_max, 1),
            "is_peak": month_peak and month_counts[month] == month_peak,
        }
        for month in period.months()
    ]
    month_ticks = [{"value": t, "percent": round(100 * t / axis_max, 1)} for t in ticks]

    outcome_labels = SHORT_OUTCOMES
    outcome_counter = Counter({outcome_labels[k]: v for k, v in outcomes.items() if k})
    if awaiting:
        outcome_counter["Awaiting outcome"] = awaiting
    if upcoming:
        outcome_counter["Upcoming"] = upcoming

    delivered = Counter(dict(Modality.choices)[r.modality] for r in rows if r.outcome in SERVED)
    sites = Counter(r.location.name if r.location else "No site" for r in rows)
    departments = Counter(r.department.name if r.department else "No department" for r in rows)
    services = Counter(r.get_service_type_display() for r in rows)
    employment = Counter()
    for r in rows:
        if r.outcome == Outcome.COMPLETED and r.interpreter:
            employment[r.interpreter.get_employment_display()] += r.billable_minutes
    employment_hours = Counter({k: round(v / 60) for k, v in employment.items()})

    return {
        "period": period,
        "generated_at": now,
        "total": len(rows),
        "needed": needed,
        "served": served,
        "fill_rate": _rate(served, needed),
        "certified_rate": _rate(certified, len(completed)),
        "unfilled": outcomes[Outcome.UNFILLED],
        "cancelled": outcomes[Outcome.CANCELLED],
        "client_declined": outcomes[Outcome.CLIENT_DECLINED],
        "client_no_show": outcomes[Outcome.CLIENT_NO_SHOW],
        "interpreter_no_show": outcomes[Outcome.INTERPRETER_NO_SHOW],
        "vendor_line": outcomes[Outcome.VENDOR_LINE],
        "awaiting": awaiting,
        "upcoming": upcoming,
        "fallbacks": sum(1 for r in rows if r.fell_back_to_video),
        "hours": round(minutes / 60, 1),
        "median_lead_hours": round(statistics.median(lead_hours), 1) if lead_hours else None,
        "median_lead": _duration(statistics.median(lead_hours)) if lead_hours else None,
        "median_fill_minutes": round(statistics.median(fill_minutes)) if fill_minutes else None,
        "languages": languages,
        "language_count": len(languages),
        "months": months,
        "month_ticks": month_ticks,
        "outcomes": _bars(outcome_counter, total=len(rows)),
        "modalities": _bars(delivered, total=served),
        "sites": _bars(sites, total=len(rows)),
        "departments": _bars(departments, total=len(rows)),
        "services": _bars(services, total=len(rows)),
        "employment_hours": _bars(employment_hours),
    }


# --- CSV --------------------------------------------------------------------

LOG_COLUMNS = [
    "reference",
    "language",
    "service_type",
    "requested_modality",
    "delivered_modality",
    "fell_back_to_video",
    "starts_at",
    "ends_at",
    "site",
    "department",
    "appointment_ref",
    "requested_by",
    "requested_at",
    "assigned_at",
    "minutes_to_fill",
    "interpreter",
    "interpreter_type",
    "credential",
    "status",
    "outcome",
    "minutes_interpreted",
    "outcome_recorded_at",
    "cancel_reason",
]


def _iso(value: dt.datetime | None) -> str:
    return timezone.localtime(value).isoformat(timespec="minutes") if value else ""


def request_log_csv(period: Period) -> str:
    rows = list(_requests(period))
    credentials = _credentials(rows)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(LOG_COLUMNS)
    for r in rows:
        fill = ""
        if r.assigned_at:
            fill = str(round((r.assigned_at - r.created_at).total_seconds() / 60))
        writer.writerow(
            [
                r.reference,
                r.language.name,
                r.get_service_type_display(),
                dict(Modality.choices)[r.requested_modality],
                r.get_modality_display(),
                "yes" if r.fell_back_to_video else "no",
                _iso(r.starts_at),
                _iso(r.ends_at),
                r.location.name if r.location else "",
                r.department.name if r.department else "",
                r.appointment_ref,
                r.requested_by.get_username() if r.requested_by else "",
                _iso(r.created_at),
                _iso(r.assigned_at),
                fill,
                r.interpreter.name if r.interpreter else "",
                r.interpreter.get_employment_display() if r.interpreter else "",
                credentials.get((r.interpreter_id, r.language_id), "") if r.interpreter else "",
                r.get_status_display(),
                r.get_outcome_display() if r.outcome else "",
                r.actual_minutes or (r.duration_minutes if r.outcome in SERVED else ""),
                _iso(r.outcome_recorded_at),
                r.cancel_reason,
            ]
        )
    return buffer.getvalue()


def summary_csv(report: dict) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Language access report", report["period"].label])
    writer.writerow([])
    for label, key in [
        ("Requests", "total"),
        ("Needed an interpreter", "needed"),
        ("Interpreter provided", "served"),
        ("Fill rate (%)", "fill_rate"),
        ("Certified interpreter (%)", "certified_rate"),
        ("Unfilled", "unfilled"),
        ("Covered by outside line", "vendor_line"),
        ("Interpreter did not attend", "interpreter_no_show"),
        ("Client declined (documented)", "client_declined"),
        ("Client did not attend", "client_no_show"),
        ("Cancelled", "cancelled"),
        ("Switched to video", "fallbacks"),
        ("Interpreter hours", "hours"),
        ("Median lead time (hours)", "median_lead_hours"),
        ("Median time to fill (minutes)", "median_fill_minutes"),
        ("Awaiting outcome", "awaiting"),
    ]:
        value = report[key]
        writer.writerow([label, "" if value is None else value])
    writer.writerow([])
    writer.writerow(
        ["Language", "Requests", "Needed", "Provided", "Unfilled", "Fill rate (%)", "Hours"]
    )
    for entry in report["languages"]:
        writer.writerow(
            [
                entry["language"],
                entry["requests"],
                entry["needed"],
                entry["served"],
                entry["unfilled"],
                "" if entry["fill_rate"] is None else entry["fill_rate"],
                entry["hours"],
            ]
        )
    return buffer.getvalue()
