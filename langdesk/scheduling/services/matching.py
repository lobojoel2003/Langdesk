"""Rank interpreters for a request.

Matching runs in two passes. Hard rules remove anyone who cannot take the job: wrong
language or mode, a site they don't travel to, time off, outside working hours, already
booked, at their daily limit, or they already said no. Everyone left gets a score, and
each point comes with a short reason the coordinator can read on the board.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field

from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.formats import date_format

from langdesk.roster.models import Interpreter, InterpreterLanguage

from ..models import InterpreterRequest, Modality, Offer

CERTIFIED_POINTS = 30
QUALIFIED_POINTS = 20
STAFF_POINTS = 15
CONTRACTOR_POINTS = 5
SAME_SITE_POINTS = 15
CONTINUITY_POINTS = 10
RELIABLE_POINTS = 5
PER_JOB_TODAY = 6
PER_JOB_THIS_WEEK = 1
MAX_SCORE = CERTIFIED_POINTS + STAFF_POINTS + SAME_SITE_POINTS + CONTINUITY_POINTS + RELIABLE_POINTS

BOOKED_STATUSES = [InterpreterRequest.Status.ASSIGNED, InterpreterRequest.Status.CLOSED]


@dataclass
class Candidate:
    interpreter: Interpreter
    score: int
    credential: str
    reasons: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    offer: Offer | None = None

    @property
    def percent(self) -> int:
        return max(4, min(100, round(100 * self.score / MAX_SCORE)))

    @property
    def is_fresh(self) -> bool:
        """Not yet asked (or asked before and the offer was withdrawn)."""
        return self.offer is None or self.offer.status == Offer.Status.WITHDRAWN


@dataclass
class Exclusion:
    interpreter: Interpreter
    reason: str


@dataclass
class Match:
    candidates: list[Candidate]
    excluded: list[Exclusion]

    def fresh(self, limit: int | None = None) -> list[Candidate]:
        found = [c for c in self.candidates if c.is_fresh]
        return found[:limit] if limit else found


def _overlaps(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end


def _local_day_bounds(moment: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    local = timezone.localtime(moment)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + dt.timedelta(days=1)


def match(req: InterpreterRequest) -> Match:
    """Return ranked candidates and the people ruled out (with why) for ``req``."""
    skills = list(
        InterpreterLanguage.objects.filter(language=req.language, interpreter__is_active=True)
        .select_related("interpreter", "interpreter__home_location")
        .prefetch_related(
            "interpreter__serves_locations", "interpreter__availability", "interpreter__time_off"
        )
    )
    ids = [skill.interpreter_id for skill in skills]

    day_start, day_end = _local_day_bounds(req.starts_at)
    week_start = day_start - dt.timedelta(days=day_start.weekday())
    week_end = week_start + dt.timedelta(days=7)
    window_start = min(week_start, req.starts_at - dt.timedelta(hours=12))
    window_end = max(week_end, req.ends_at + dt.timedelta(hours=12))

    bookings: dict[int, list[InterpreterRequest]] = defaultdict(list)
    for booking in (
        InterpreterRequest.objects.filter(
            interpreter_id__in=ids,
            status__in=BOOKED_STATUSES,
            starts_at__lt=window_end,
            ends_at__gt=window_start,
        )
        .exclude(pk=req.pk)
        .exclude(outcome=InterpreterRequest.Outcome.CANCELLED)
        .only("interpreter_id", "starts_at", "ends_at", "modality", "location_id")
    ):
        bookings[booking.interpreter_id].append(booking)

    latest_offer: dict[int, Offer] = {}
    if req.pk:
        for offer in req.offers.order_by("sent_at", "pk"):
            latest_offer[offer.interpreter_id] = offer

    stats = {
        row["interpreter_id"]: row
        for row in Offer.objects.filter(interpreter_id__in=ids)
        .exclude(status=Offer.Status.PENDING)
        .values("interpreter_id")
        .annotate(total=Count("id"), accepted=Count("id", filter=Q(status=Offer.Status.ACCEPTED)))
    }

    worked_case: set[int] = set()
    if req.appointment_ref:
        worked_case = set(
            InterpreterRequest.objects.filter(
                appointment_ref=req.appointment_ref, interpreter_id__in=ids
            )
            .exclude(pk=req.pk)
            .values_list("interpreter_id", flat=True)
        )

    buffer = dt.timedelta(minutes=settings.LANGDESK_TRAVEL_BUFFER_MINUTES)
    candidates: list[Candidate] = []
    excluded: list[Exclusion] = []

    for skill in skills:
        person = skill.interpreter
        if person.pk == req.interpreter_id:
            continue
        reason = _rule_out(req, person, bookings[person.pk], latest_offer.get(person.pk), buffer)
        if reason:
            excluded.append(Exclusion(person, reason))
            continue

        credential = skill.effective_credential
        score = 0
        reasons: list[str] = []
        cautions: list[str] = []

        if credential == InterpreterLanguage.Credential.CERTIFIED:
            score += CERTIFIED_POINTS
            reasons.append("Certified")
        else:
            score += QUALIFIED_POINTS
            reasons.append("Qualified")
            if skill.is_expired:
                cautions.append("Certification expired")

        if person.employment == Interpreter.Employment.STAFF:
            score += STAFF_POINTS
            reasons.append("Staff")
        elif person.employment == Interpreter.Employment.CONTRACTOR:
            score += CONTRACTOR_POINTS
            reasons.append("Contractor")
        else:
            reasons.append(person.agency_name or "Agency")

        if (
            req.modality == Modality.IN_PERSON
            and req.location_id
            and person.home_location_id == req.location_id
        ):
            score += SAME_SITE_POINTS
            reasons.append("Same site")

        if person.pk in worked_case:
            score += CONTINUITY_POINTS
            reasons.append("Knows this case")

        record = stats.get(person.pk)
        if record and record["total"] >= 5 and record["accepted"] / record["total"] >= 0.7:
            score += RELIABLE_POINTS
            reasons.append("Reliable")

        same_day = [b for b in bookings[person.pk] if day_start <= b.starts_at < day_end]
        this_week = [b for b in bookings[person.pk] if week_start <= b.starts_at < week_end]
        score -= PER_JOB_TODAY * len(same_day) + PER_JOB_THIS_WEEK * len(this_week)
        if same_day:
            cautions.append(f"{len(same_day)} job{'s' if len(same_day) > 1 else ''} that day")
        else:
            reasons.append("Free that day")

        candidates.append(
            Candidate(
                interpreter=person,
                score=max(score, 0),
                credential=credential,
                reasons=reasons,
                cautions=cautions,
                offer=latest_offer.get(person.pk),
            )
        )

    candidates.sort(key=lambda c: (-c.score, c.interpreter.name))
    excluded.sort(key=lambda e: e.interpreter.name)
    return Match(candidates=candidates, excluded=excluded)


def _rule_out(
    req: InterpreterRequest,
    person: Interpreter,
    bookings: list[InterpreterRequest],
    offer: Offer | None,
    buffer: dt.timedelta,
) -> str:
    """Return why ``person`` cannot take ``req``, or an empty string if they can."""
    if not person.supports(req.modality):
        return f"Does not work {req.get_modality_display().lower()}"
    if not person.can_text and not person.email:
        return "No way to reach them"
    if offer and offer.status == Offer.Status.DECLINED:
        return "Declined this request"

    if req.modality == Modality.IN_PERSON and req.location_id:
        sites = {site.pk for site in person.serves_locations.all()}
        if sites and req.location_id not in sites and person.home_location_id != req.location_id:
            return f"Does not travel to {req.location}"

    for leave in person.time_off.all():
        if _overlaps(leave.starts_at, leave.ends_at, req.starts_at, req.ends_at):
            return "On time off"

    windows = list(person.availability.all())
    if windows and not any(window.covers(req.starts_at, req.ends_at) for window in windows):
        return "Outside working hours"

    for booking in bookings:
        pad = buffer if Modality.IN_PERSON in (booking.modality, req.modality) else dt.timedelta()
        if _overlaps(booking.starts_at - pad, booking.ends_at + pad, req.starts_at, req.ends_at):
            return f"Booked at {date_format(timezone.localtime(booking.starts_at), 'g:i A')}"

    if person.max_daily_assignments:
        day_start, day_end = _local_day_bounds(req.starts_at)
        same_day = sum(1 for b in bookings if day_start <= b.starts_at < day_end)
        if same_day >= person.max_daily_assignments:
            return "Reached daily limit"

    return ""
