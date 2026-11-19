"""Every state change to a request goes through here.

Each function writes a :class:`RequestEvent` (the audit log regulators ask for) and sends
the messages that go with the change. Views, the SMS webhook and the periodic dispatcher
all call these functions, so the rules live in one place.
"""

from __future__ import annotations

import datetime as dt

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from langdesk.roster.models import Interpreter

from ..models import InterpreterRequest, Modality, Offer, RequestEvent
from ..video import new_video_link
from . import notify
from .matching import Candidate, match

Status = InterpreterRequest.Status
Outcome = InterpreterRequest.Outcome
Kind = RequestEvent.Kind


class DispatchError(Exception):
    """An action that isn't allowed in the request's current state."""


def log(req, kind, message, *, actor=None, interpreter=None) -> RequestEvent:
    return RequestEvent.objects.create(
        request=req, kind=kind, message=message[:255], actor=actor, interpreter=interpreter
    )


def _names(people: list[Interpreter]) -> str:
    names = [person.name for person in people]
    if len(names) <= 2:
        return " and ".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _locked(req: InterpreterRequest) -> InterpreterRequest:
    return InterpreterRequest.objects.select_for_update().get(pk=req.pk)


# --- Creating and editing ---------------------------------------------------


def create_request(req: InterpreterRequest, actor) -> InterpreterRequest:
    req.requested_by = actor
    req.requested_modality = req.modality
    if req.modality == Modality.VIDEO and not req.video_url:
        req.video_url = new_video_link()
    req.save()
    log(
        req,
        Kind.CREATED,
        f"Requested {req.language} {req.get_modality_display().lower()} for "
        f"{notify.format_when(req)}",
        actor=actor,
    )
    if settings.LANGDESK_AUTO_DISPATCH:
        send_offer_wave(req)
    return req


SCHEDULE_FIELDS = {"starts_at", "ends_at", "modality", "location", "location_detail"}


def update_request(req: InterpreterRequest, changed: list[str], actor) -> InterpreterRequest:
    """Record an edit and tell whoever is affected. ``req`` is already saved."""
    if not changed:
        return req
    schedule_changed = bool(SCHEDULE_FIELDS & set(changed))
    if "modality" in changed:
        req.requested_modality = req.modality
        req.fell_back_to_video = False
    if req.modality == Modality.VIDEO and not req.video_url:
        req.video_url = new_video_link()
    if schedule_changed:
        req.sequence += 1
    req.save()
    log(req, Kind.UPDATED, f"Changed {', '.join(sorted(changed))}", actor=actor)

    if not schedule_changed:
        return req
    if req.status == Status.ASSIGNED and req.interpreter:
        notify.update(req)
    elif req.status == Status.OPEN:
        pending = list(req.pending_offers().select_related("interpreter"))
        if pending:
            req.pending_offers().update(status=Offer.Status.WITHDRAWN)
            log(
                req,
                Kind.UPDATED,
                f"Re-offering with new details: {_names([o.interpreter for o in pending])}",
            )
        if settings.LANGDESK_AUTO_DISPATCH:
            send_offer_wave(req)
    return req


# --- Offers -----------------------------------------------------------------


def _new_code(interpreter: Interpreter) -> str:
    from langdesk.core.tokens import reply_code

    taken = set(
        Offer.objects.pending().filter(interpreter=interpreter).values_list("code", flat=True)
    )
    code = reply_code()
    while code in taken:
        code = reply_code()
    return code


def _make_offer(req, candidate: Candidate, *, wave: int, actor=None, now=None) -> Offer:
    now = now or timezone.now()
    expires = now + dt.timedelta(minutes=settings.LANGDESK_OFFER_TIMEOUT_MINUTES)
    if req.starts_at > now:
        expires = min(expires, req.starts_at)
    offer = Offer.objects.create(
        request=req,
        interpreter=candidate.interpreter,
        code=_new_code(candidate.interpreter),
        score=candidate.score,
        reasons=candidate.reasons,
        wave=wave,
        sent_at=now,
        expires_at=expires,
        sent_by=actor,
    )
    notify.offer(offer)
    return offer


def _next_wave(req) -> int:
    last = req.offers.order_by("-wave").values_list("wave", flat=True).first()
    return (last or 0) + 1


def send_offer_wave(req: InterpreterRequest, *, actor=None, size=None, now=None) -> list[Offer]:
    """Offer ``req`` to the next best interpreters who haven't been asked yet."""
    now = now or timezone.now()
    if req.status != Status.OPEN or req.ends_at <= now:
        return []
    size = size or settings.LANGDESK_OFFER_WAVE_SIZE
    fresh = match(req).fresh(size)
    if not fresh:
        if not req.pending_offers().exists():
            _alert_exhausted(req)
        return []
    wave = _next_wave(req)
    offers = [_make_offer(req, c, wave=wave, actor=actor, now=now) for c in fresh]
    log(req, Kind.OFFERED, f"Offered to {_names([o.interpreter for o in offers])}", actor=actor)
    return offers


def offer_to(req: InterpreterRequest, interpreter: Interpreter, actor) -> Offer:
    if req.status != Status.OPEN:
        raise DispatchError("Only open requests can be offered.")
    found = match(req)
    candidate = next((c for c in found.candidates if c.interpreter.pk == interpreter.pk), None)
    if candidate is None:
        reason = next((e.reason for e in found.excluded if e.interpreter.pk == interpreter.pk), "")
        raise DispatchError(
            f"{interpreter} can't take this request{': ' + reason if reason else ''}."
        )
    if candidate.offer and candidate.offer.status == Offer.Status.PENDING:
        raise DispatchError(f"{interpreter} already has this offer.")
    offer = _make_offer(req, candidate, wave=_next_wave(req), actor=actor)
    log(req, Kind.OFFERED, f"Offered to {interpreter.name}", actor=actor, interpreter=interpreter)
    return offer


def _alert_exhausted(req: InterpreterRequest) -> None:
    problem = "no available interpreter is left to offer it to"
    if notify.coordinators(
        req, problem, dedupe=f"exhausted:{req.pk}:{req.modality}:{req.sequence}"
    ):
        log(req, Kind.ALERT, f"Coordinators alerted: {problem}")


def _withdraw_pending(req, *, cancelled: bool = False, exclude: Offer | None = None) -> None:
    pending = req.pending_offers().select_related("interpreter", "request")
    if exclude:
        pending = pending.exclude(pk=exclude.pk)
    for offer in pending:
        offer.status = Offer.Status.WITHDRAWN
        offer.save(update_fields=["status"])
        notify.filled(offer, cancelled=cancelled)


class Reply:
    ACCEPTED = "accepted"
    FILLED = "filled"
    DECLINED = "declined"
    NOT_PENDING = "not_pending"


def accept_offer(offer: Offer, *, channel: str) -> str:
    """Accept ``offer``. First to accept wins; everyone else is told it's filled."""
    with transaction.atomic():
        req = _locked(offer.request)
        offer = Offer.objects.select_for_update().get(pk=offer.pk)
        if offer.status == Offer.Status.ACCEPTED and req.interpreter_id == offer.interpreter_id:
            return Reply.ACCEPTED
        if req.status != Status.OPEN or req.ends_at <= timezone.now():
            if offer.status == Offer.Status.PENDING:
                offer.status = Offer.Status.WITHDRAWN
                offer.save(update_fields=["status"])
            return Reply.FILLED
        offer.status = Offer.Status.ACCEPTED
        offer.responded_at = timezone.now()
        offer.response_channel = channel
        offer.save(update_fields=["status", "responded_at", "response_channel"])
        log(
            req,
            Kind.ACCEPTED,
            f"{offer.interpreter.name} accepted by {channel}",
            interpreter=offer.interpreter,
        )
        _assign(req, offer.interpreter, offer=offer)
    return Reply.ACCEPTED


def decline_offer(offer: Offer, *, channel: str) -> str:
    with transaction.atomic():
        req = _locked(offer.request)
        offer = Offer.objects.select_for_update().get(pk=offer.pk)
        if offer.status not in {Offer.Status.PENDING, Offer.Status.EXPIRED}:
            return Reply.NOT_PENDING
        offer.status = Offer.Status.DECLINED
        offer.responded_at = timezone.now()
        offer.response_channel = channel
        offer.save(update_fields=["status", "responded_at", "response_channel"])
        log(
            req,
            Kind.DECLINED,
            f"{offer.interpreter.name} declined by {channel}",
            interpreter=offer.interpreter,
        )
        if (
            settings.LANGDESK_AUTO_DISPATCH
            and req.status == Status.OPEN
            and not req.pending_offers().exists()
        ):
            send_offer_wave(req)
    return Reply.DECLINED


def expire_offers(now=None) -> int:
    now = now or timezone.now()
    expired = list(
        Offer.objects.pending().filter(expires_at__lte=now).select_related("interpreter", "request")
    )
    by_request: dict[int, list[Offer]] = {}
    for offer in expired:
        by_request.setdefault(offer.request_id, []).append(offer)
    Offer.objects.filter(pk__in=[o.pk for o in expired]).update(status=Offer.Status.EXPIRED)
    for offers in by_request.values():
        req = offers[0].request
        if req.status == Status.OPEN:
            log(req, Kind.EXPIRED, f"No reply from {_names([o.interpreter for o in offers])}")
    return len(expired)


# --- Assignment -------------------------------------------------------------


def _assign(req: InterpreterRequest, interpreter: Interpreter, *, actor=None, offer=None) -> None:
    req.interpreter = interpreter
    req.status = Status.ASSIGNED
    req.assigned_at = timezone.now()
    req.sequence += 1
    req.save(update_fields=["interpreter", "status", "assigned_at", "sequence", "updated_at"])
    _withdraw_pending(req, exclude=offer)
    how = "from an offer" if offer else "directly"
    log(
        req,
        Kind.ASSIGNED,
        f"{interpreter.name} assigned {how}",
        actor=actor,
        interpreter=interpreter,
    )
    notify.confirmation(req)
    notify.requester(req, "assigned")


def assign(req: InterpreterRequest, interpreter: Interpreter, actor) -> InterpreterRequest:
    """Coordinator override: assign ``interpreter`` without waiting for a reply."""
    with transaction.atomic():
        req = _locked(req)
        if req.status not in {Status.OPEN, Status.ASSIGNED}:
            raise DispatchError("This request is closed.")
        if (
            not interpreter.is_active
            or not interpreter.languages.filter(pk=req.language_id).exists()
        ):
            raise DispatchError(f"{interpreter} doesn't interpret {req.language}.")
        if req.interpreter_id == interpreter.pk:
            return req
        if req.status == Status.ASSIGNED and req.interpreter:
            _release(req, actor, reason="Reassigned to another interpreter")
        offer = req.pending_offers().filter(interpreter=interpreter).first()
        if offer:
            offer.status = Offer.Status.ACCEPTED
            offer.responded_at = timezone.now()
            offer.response_channel = "coordinator"
            offer.save(update_fields=["status", "responded_at", "response_channel"])
        _assign(req, interpreter, actor=actor, offer=offer)
    return req


def _release(req: InterpreterRequest, actor, *, reason: str) -> Interpreter:
    previous = req.interpreter
    assert previous is not None  # noqa: S101 - guarded by callers
    req.offers.filter(interpreter=previous, status=Offer.Status.ACCEPTED).update(
        status=Offer.Status.DECLINED
    )
    req.interpreter = None
    req.status = Status.OPEN
    req.assigned_at = None
    req.sequence += 1
    req.save(update_fields=["interpreter", "status", "assigned_at", "sequence", "updated_at"])
    log(
        req,
        Kind.UNASSIGNED,
        f"{previous.name} unassigned: {reason}",
        actor=actor,
        interpreter=previous,
    )
    notify.cancellation(req, previous, reason)
    return previous


def unassign(req: InterpreterRequest, actor, reason: str = "") -> InterpreterRequest:
    """The interpreter can't make it. Reopen and offer to the next people in line."""
    reason = reason or "Interpreter no longer available"
    with transaction.atomic():
        req = _locked(req)
        if req.status != Status.ASSIGNED or not req.interpreter:
            raise DispatchError("Nobody is assigned to this request.")
        _release(req, actor, reason=reason)
        notify.requester(req, "unassigned", reason=reason)
        if settings.LANGDESK_AUTO_DISPATCH:
            send_offer_wave(req, actor=actor)
    return req


def cancel(req: InterpreterRequest, actor, reason: str = "") -> InterpreterRequest:
    with transaction.atomic():
        req = _locked(req)
        if not req.is_active:
            raise DispatchError("This request is already closed.")
        previous = req.interpreter
        now = timezone.now()
        req.status = Status.CANCELLED
        req.cancelled_at = now
        req.cancel_reason = reason[:200]
        req.outcome = Outcome.CANCELLED
        req.outcome_recorded_at = now
        req.outcome_recorded_by = actor
        req.sequence += 1
        req.save()
        _withdraw_pending(req, cancelled=True)
        log(req, Kind.CANCELLED, f"Cancelled{': ' + reason if reason else ''}", actor=actor)
        if previous:
            notify.cancellation(req, previous, reason)
        if actor != req.requested_by:
            notify.requester(req, "cancelled", reason=reason)
    return req


# --- Video fallback ---------------------------------------------------------


def fall_back_to_video(req: InterpreterRequest, actor=None) -> bool:
    """Switch an unfilled in-person request to video and widen the search."""
    with transaction.atomic():
        req = _locked(req)
        if req.status != Status.OPEN or req.modality != Modality.IN_PERSON:
            return False
        req.modality = Modality.VIDEO
        req.video_url = req.video_url or new_video_link()
        req.fell_back_to_video = True
        req.sequence += 1
        req.save()
        who = "" if actor else " automatically"
        log(
            req,
            Kind.VIDEO_FALLBACK,
            f"Switched to video{who}: no in-person interpreter confirmed",
            actor=actor,
        )
        notify.requester(req, "video_fallback")
        if settings.LANGDESK_AUTO_DISPATCH:
            send_offer_wave(req, actor=actor)
    return True


# --- Outcomes ---------------------------------------------------------------

NEEDS_INTERPRETER = {Outcome.COMPLETED, Outcome.INTERPRETER_NO_SHOW}


def record_outcome(
    req: InterpreterRequest,
    *,
    outcome: str,
    actor,
    actual_minutes: int | None = None,
    notes: str = "",
) -> InterpreterRequest:
    with transaction.atomic():
        req = _locked(req)
        if req.status == Status.CANCELLED:
            raise DispatchError("Cancelled requests already have an outcome.")
        if outcome in NEEDS_INTERPRETER and not req.interpreter:
            raise DispatchError(
                "Assign the interpreter who attended before recording this outcome."
            )
        req.status = Status.CLOSED
        req.outcome = outcome
        req.actual_minutes = actual_minutes
        req.outcome_notes = notes
        req.outcome_recorded_at = timezone.now()
        req.outcome_recorded_by = actor
        req.save()
        _withdraw_pending(req, cancelled=True)
        log(req, Kind.OUTCOME, f"Outcome: {req.get_outcome_display()}", actor=actor)
    return req


# --- Reminders --------------------------------------------------------------


def send_due_reminders(now=None) -> int:
    """Send at most one reminder per request per run: the closest lead time that's due."""
    now = now or timezone.now()
    leads = sorted(set(settings.LANGDESK_REMINDER_MINUTES))
    if not leads:
        return 0
    horizon = now + dt.timedelta(minutes=max(leads))
    sent = 0
    for req in (
        InterpreterRequest.objects.assigned()
        .filter(starts_at__gt=now, starts_at__lte=horizon)
        .select_related("interpreter", "language", "location")
    ):
        until = req.starts_at - now
        due = [
            lead
            for lead in leads
            if until <= dt.timedelta(minutes=lead)
            and req.assigned_at
            and req.assigned_at < req.starts_at - dt.timedelta(minutes=lead)
        ]
        if not due:
            continue
        lead = min(due)
        if notify.reminder(req, lead):
            sent += 1
            log(
                req,
                Kind.REMINDER,
                f"Reminder sent to {req.interpreter.name}",
                interpreter=req.interpreter,
            )
    return sent


# --- Periodic run -----------------------------------------------------------


def run_dispatcher(now=None) -> dict[str, int]:
    """One pass of the background loop. Safe to run as often as you like."""
    now = now or timezone.now()
    stats = {"expired": expire_offers(now), "fallbacks": 0, "waves": 0, "reminders": 0}

    lead = settings.LANGDESK_VIDEO_FALLBACK_MINUTES
    if lead > 0:
        for req in InterpreterRequest.objects.open().filter(
            modality=Modality.IN_PERSON,
            starts_at__lte=now + dt.timedelta(minutes=lead),
            ends_at__gt=now,
        ):
            stats["fallbacks"] += fall_back_to_video(req)

    if settings.LANGDESK_AUTO_DISPATCH:
        waiting = (
            InterpreterRequest.objects.open()
            .filter(ends_at__gt=now)
            .exclude(offers__status=Offer.Status.PENDING)
            .select_related("language", "location")
        )
        for req in waiting:
            if send_offer_wave(req, now=now):
                stats["waves"] += 1

    stats["reminders"] = send_due_reminders(now)
    return stats
