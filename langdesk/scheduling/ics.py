"""iCalendar output: invites attached to emails and a subscribable feed per interpreter."""

from __future__ import annotations

import datetime as dt
from email.utils import parseaddr
from urllib.parse import urlparse

from django.conf import settings
from django.utils import timezone
from icalendar import Alarm, Calendar, Event, vCalAddress, vText

from langdesk.roster.models import Interpreter
from langdesk.version import __version__

from .models import InterpreterRequest, Modality

PRODID = f"-//Langdesk//Langdesk {__version__}//EN"


def _host() -> str:
    return urlparse(settings.LANGDESK_BASE_URL).hostname or "langdesk.local"


def uid_for(req: InterpreterRequest) -> str:
    return f"request-{req.pk}@{_host()}"


def _location_text(req: InterpreterRequest) -> str:
    if req.modality == Modality.VIDEO:
        return req.video_url or "Video call"
    if req.modality == Modality.PHONE:
        return "Phone call"
    parts = [req.location.name if req.location else "", req.location_detail]
    if req.location and req.location.address:
        parts.append(req.location.address.replace("\n", ", "))
    return ", ".join(part for part in parts if part)


def _description(req: InterpreterRequest) -> str:
    lines = [
        f"{req.language} interpreting ({req.get_modality_display().lower()})",
        f"Reference: {req.reference}",
    ]
    if req.appointment_ref:
        lines.append(f"Appointment: {req.appointment_ref}")
    if req.department:
        lines.append(f"Department: {req.department}")
    if req.video_url:
        lines.append(f"Video link: {req.video_url}")
    if req.modality == Modality.IN_PERSON and req.location and req.location.arrival_instructions:
        lines.append(f"Arrival: {req.location.arrival_instructions}")
    if req.notes:
        lines.append(f"Notes: {req.notes}")
    lines.append(f"Details: {settings.LANGDESK_BASE_URL}{req.get_absolute_url()}")
    return "\n".join(lines)


def build_event(req: InterpreterRequest, *, cancelled: bool = False) -> Event:
    event = Event()
    event.add("uid", uid_for(req))
    event.add("dtstamp", timezone.now())
    event.add("dtstart", req.starts_at.astimezone(dt.UTC))
    event.add("dtend", req.ends_at.astimezone(dt.UTC))
    event.add("summary", f"Interpreting: {req.language} · {req.reference}")
    event.add("location", _location_text(req))
    event.add("description", _description(req))
    event.add("sequence", req.sequence)
    event.add("status", "CANCELLED" if cancelled else "CONFIRMED")
    event.add("transp", "OPAQUE")
    event.add("categories", ["Interpreting", req.language.name])
    if req.video_url:
        event.add("url", req.video_url)
    if not cancelled:
        alarm = Alarm()
        alarm.add("action", "DISPLAY")
        alarm.add("description", vText(f"Interpreting: {req.language} in 1 hour"))
        alarm.add("trigger", dt.timedelta(hours=-1))
        event.add_component(alarm)
    return event


def _calendar(name: str | None = None, method: str | None = None) -> Calendar:
    cal = Calendar()
    cal.add("prodid", PRODID)
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    if method:
        cal.add("method", method)
    if name:
        cal.add("x-wr-calname", name)
        cal.add("x-wr-timezone", settings.TIME_ZONE)
        cal.add("refresh-interval", dt.timedelta(hours=1), parameters={"VALUE": "DURATION"})
        cal.add("x-published-ttl", "PT1H")
    return cal


def invite(req: InterpreterRequest, interpreter: Interpreter, *, cancelled: bool = False) -> str:
    """An iTIP invite (``METHOD:REQUEST`` or ``METHOD:CANCEL``) for an email attachment."""
    cal = _calendar(method="CANCEL" if cancelled else "REQUEST")
    event = build_event(req, cancelled=cancelled)
    _, from_address = parseaddr(settings.DEFAULT_FROM_EMAIL)
    organizer = vCalAddress(f"mailto:{from_address}")
    organizer.params["cn"] = vText(settings.LANGDESK_ORG_NAME)
    event.add("organizer", organizer)
    if interpreter.email:
        attendee = vCalAddress(f"mailto:{interpreter.email}")
        attendee.params["cn"] = vText(interpreter.name)
        attendee.params["role"] = vText("REQ-PARTICIPANT")
        attendee.params["partstat"] = vText("ACCEPTED")
        attendee.params["rsvp"] = vText("FALSE")
        event.add("attendee", attendee, encode=0)
    cal.add_component(event)
    return cal.to_ical().decode()


def single(req: InterpreterRequest) -> bytes:
    """A plain one-event calendar file for staff to add to their own calendar."""
    cal = _calendar(method="PUBLISH")
    cal.add_component(build_event(req, cancelled=req.status == req.Status.CANCELLED))
    return cal.to_ical()


def feed(interpreter: Interpreter) -> bytes:
    """Upcoming and recent assignments for ``interpreter`` as a subscribable feed."""
    since = timezone.now() - dt.timedelta(days=settings.LANGDESK_FEED_PAST_DAYS)
    assignments = (
        InterpreterRequest.objects.filter(interpreter=interpreter, ends_at__gte=since)
        .exclude(status=InterpreterRequest.Status.CANCELLED)
        .select_related("language", "location", "department")
    )
    cal = _calendar(name=f"{settings.LANGDESK_ORG_NAME} · {interpreter.name}")
    for req in assignments:
        cal.add_component(build_event(req))
    return cal.to_ical()
