"""Compose the texts and emails Langdesk sends about a request.

Wording lives in ``scheduling/templates/scheduling/messages/`` so an organisation can
override or translate it. Messages never include client details: only language, time,
place and the appointment reference.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.formats import date_format

from langdesk.core.roles import COORDINATORS
from langdesk.messaging.models import Notification
from langdesk.messaging.services import queue_email, queue_sms
from langdesk.roster.models import Interpreter

from .. import ics
from ..models import InterpreterRequest, Modality, Offer

Kind = Notification.Kind


def format_when(req: InterpreterRequest) -> str:
    start = timezone.localtime(req.starts_at)
    end = timezone.localtime(req.ends_at)
    day = date_format(start, "D M j")
    if start.date() != end.date():
        return f"{day}, {date_format(start, 'g:i A')} to {date_format(end, 'D M j, g:i A')}"
    if date_format(start, "A") == date_format(end, "A"):
        return f"{day}, {date_format(start, 'g:i')}–{date_format(end, 'g:i A')}"
    return f"{day}, {date_format(start, 'g:i A')}–{date_format(end, 'g:i A')}"


def mode_phrase(req: InterpreterRequest) -> str:
    if req.modality == Modality.VIDEO:
        return "by video"
    if req.modality == Modality.PHONE:
        return "by phone"
    return f"in person at {req.place}" if req.place else "in person"


def absolute(path: str) -> str:
    return f"{settings.LANGDESK_BASE_URL}{path}"


def _context(req: InterpreterRequest, **extra) -> dict:
    return {
        "req": req,
        "org": settings.LANGDESK_ORG_NAME,
        "when": format_when(req),
        "mode": mode_phrase(req),
        "request_url": absolute(req.get_absolute_url()),
        "support": settings.LANGDESK_SUPPORT_CONTACT,
        **extra,
    }


def _render(name: str, context: dict) -> str:
    return render_to_string(f"scheduling/messages/{name}", context)


def _to_interpreter(
    interpreter: Interpreter,
    req: InterpreterRequest,
    kind: str,
    template: str,
    context: dict,
    *,
    subject: str,
    ics_text: str = "",
    dedupe: str | None = None,
    email_always: bool = False,
) -> list[Notification]:
    sent: list[Notification] = []
    links = {"request": req, "interpreter": interpreter}
    if interpreter.wants("sms"):
        note = queue_sms(
            interpreter.phone,
            _render(f"{template}.sms.txt", context),
            kind=kind,
            dedupe_key=f"{dedupe}:sms" if dedupe else None,
            **links,
        )
        if note:
            sent.append(note)
    if interpreter.email and (interpreter.wants("email") or email_always):
        note = queue_email(
            interpreter.email,
            subject,
            _render(f"{template}.email.txt", context),
            kind=kind,
            ics=ics_text,
            dedupe_key=f"{dedupe}:email" if dedupe else None,
            **links,
        )
        if note:
            sent.append(note)
    return sent


# --- Interpreter messages ---------------------------------------------------


def offer(offer: Offer) -> list[Notification]:
    req = offer.request
    context = _context(req, offer=offer, offer_url=absolute(offer.get_absolute_url()))
    return _to_interpreter(
        offer.interpreter,
        req,
        Kind.OFFER,
        "offer",
        context,
        subject=f"Can you interpret {req.language}? {format_when(req)}",
    )


def filled(offer: Offer, *, cancelled: bool = False) -> list[Notification]:
    req = offer.request
    context = _context(req, offer=offer, cancelled=cancelled)
    return _to_interpreter(
        offer.interpreter,
        req,
        Kind.FILLED,
        "filled",
        context,
        subject=f"No longer needed: {req.language}, {format_when(req)}",
    )


def confirmation(req: InterpreterRequest) -> list[Notification]:
    interpreter = req.interpreter
    if interpreter is None:
        return []
    return _to_interpreter(
        interpreter,
        req,
        Kind.CONFIRMATION,
        "confirmation",
        _context(req, interpreter=interpreter),
        subject=f"Confirmed: {req.language} interpreting, {format_when(req)}",
        ics_text=ics.invite(req, interpreter),
        email_always=True,
    )


def update(req: InterpreterRequest) -> list[Notification]:
    interpreter = req.interpreter
    if interpreter is None:
        return []
    return _to_interpreter(
        interpreter,
        req,
        Kind.UPDATE,
        "update",
        _context(req, interpreter=interpreter),
        subject=f"Updated: {req.language} interpreting, {format_when(req)}",
        ics_text=ics.invite(req, interpreter),
        email_always=True,
    )


def cancellation(req: InterpreterRequest, interpreter: Interpreter, reason: str = ""):
    return _to_interpreter(
        interpreter,
        req,
        Kind.CANCELLATION,
        "cancellation",
        _context(req, interpreter=interpreter, reason=reason),
        subject=f"Cancelled: {req.language} interpreting, {format_when(req)}",
        ics_text=ics.invite(req, interpreter, cancelled=True),
        email_always=True,
    )


def reminder(req: InterpreterRequest, lead_minutes: int) -> list[Notification]:
    interpreter = req.interpreter
    if interpreter is None:
        return []
    if lead_minutes >= 120 and lead_minutes % 60 == 0:
        hours = lead_minutes // 60
        lead = "tomorrow" if hours == 24 else f"in {hours} hours"
    else:
        lead = f"in {lead_minutes} minutes"
    key = f"reminder:{req.pk}:{interpreter.pk}:{lead_minutes}:{int(req.starts_at.timestamp())}"
    return _to_interpreter(
        interpreter,
        req,
        Kind.REMINDER,
        "reminder",
        _context(req, interpreter=interpreter, lead=lead),
        subject=f"Reminder: {req.language} interpreting {lead}",
        dedupe=key,
    )


# --- Staff messages ---------------------------------------------------------

REQUESTER_SUBJECTS = {
    "assigned": "Interpreter confirmed for {ref}",
    "video_fallback": "{ref} will use video interpreting",
    "unassigned": "Finding a new interpreter for {ref}",
    "cancelled": "{ref} was cancelled",
}


def requester(req: InterpreterRequest, event: str, *, reason: str = "") -> Notification | None:
    user = req.requested_by
    if not user or not user.email:
        return None
    context = _context(req, event=event, reason=reason, interpreter=req.interpreter)
    return queue_email(
        user.email,
        REQUESTER_SUBJECTS[event].format(ref=req.reference),
        _render("requester.email.txt", context),
        kind=Kind.REQUESTER_UPDATE,
        request=req,
        recipient_user=user,
    )


def coordinators(req: InterpreterRequest, problem: str, *, dedupe: str) -> list[Notification]:
    users = (
        get_user_model()
        .objects.filter(is_active=True)
        .filter(groups__name=COORDINATORS)
        .exclude(email="")
        .distinct()
    )
    sent = []
    for user in users:
        note = queue_email(
            user.email,
            f"Action needed: {req.reference} {req.language}, {format_when(req)}",
            _render("alert.email.txt", _context(req, problem=problem)),
            kind=Kind.COORDINATOR_ALERT,
            request=req,
            recipient_user=user,
            dedupe_key=f"{dedupe}:{user.pk}",
        )
        if note:
            sent.append(note)
    return sent
