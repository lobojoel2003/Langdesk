from __future__ import annotations

import datetime as dt

from django import template
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from langdesk.scheduling.models import InterpreterRequest, Modality, Offer
from langdesk.scheduling.services.notify import format_when

register = template.Library()

_ICONS = {
    "in_person": '<circle cx="12" cy="7" r="4"/><path d="M5 21v-1a7 7 0 0 1 14 0v1"/>',
    "video": '<rect x="2.5" y="6" width="13" height="12" rx="2.5"/><path d="m15.5 10.5 6-3.5v10l-6-3.5"/>',
    "phone": '<path d="M5 3h3.5l2 5-2.5 1.5a11 11 0 0 0 6.5 6.5l1.5-2.5 5 2V19a2 2 0 0 1-2 2A17 17 0 0 1 3 5a2 2 0 0 1 2-2Z"/>',
    "pin": '<path d="M12 21s-7-6.1-7-11.5a7 7 0 0 1 14 0C19 14.9 12 21 12 21Z"/><circle cx="12" cy="9.5" r="2.5"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "calendar": '<rect x="3" y="4.5" width="18" height="16" rx="2.5"/><path d="M3 9.5h18M8 2.5v4M16 2.5v4"/>',
    "lock": '<rect x="4.5" y="10.5" width="15" height="10" rx="2.5"/><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3"/>',
    "check": '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    "x": '<path d="M6 6l12 12M18 6 6 18"/>',
    "alert": '<path d="M12 3 2 20h20L12 3Z"/><path d="M12 10v4.5M12 17.5h.01"/>',
    "message": '<path d="M4 5h16v11H9l-5 4V5Z"/>',
    "sms": '<path d="M4 5h16v11H9l-5 4V5Z"/>',
    "email": '<rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="m3.5 7 8.5 6 8.5-6"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "download": '<path d="M12 4v11m-5-5 5 5 5-5M5 20h14"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M21.5 20a6.5 6.5 0 0 0-4-6"/>',
    "chart": '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    "board": '<rect x="3" y="3" width="7.5" height="18" rx="2"/><rect x="13.5" y="3" width="7.5" height="11" rx="2"/>',
    "list": '<path d="M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01"/>',
    "link": '<path d="M10 14a4.5 4.5 0 0 0 6.4 0l3-3a4.5 4.5 0 0 0-6.4-6.4l-1 1"/><path d="M14 10a4.5 4.5 0 0 0-6.4 0l-3 3a4.5 4.5 0 0 0 6.4 6.4l1-1"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1"/>',
    "print": '<path d="M7 9V3h10v6"/><rect x="3" y="9" width="18" height="8" rx="2"/><path d="M7 14h10v7H7z"/>',
}


@register.simple_tag
def icon(name: str, size: int = 18, label: str = "") -> str:
    path = _ICONS.get(name, _ICONS["message"])
    aria = format_html('role="img" aria-label="{}"', label) if label else 'aria-hidden="true"'
    return mark_safe(
        f'<svg class="icon" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" '
        f"{aria}>{path}</svg>"
    )


@register.filter
def when(req: InterpreterRequest) -> str:
    return format_when(req)


@register.filter
def until(moment: dt.datetime) -> str:
    """``in 45 min``, ``in 3 h``, ``in 2 days`` or ``12 min ago``."""
    seconds = (moment - timezone.now()).total_seconds()
    future = seconds >= 0
    minutes = abs(seconds) / 60
    if minutes < 1:
        return "now"
    if minutes < 60:
        text = f"{int(minutes)} min"
    elif minutes < 48 * 60:
        text = f"{int(minutes // 60)} h"
    else:
        text = f"{int(minutes // (60 * 24))} days"
    return f"in {text}" if future else f"{text} ago"


@register.filter
def modality_label(value: str) -> str:
    return dict(Modality.choices).get(value, value)


@register.inclusion_tag("includes/status.html")
def status_pill(req: InterpreterRequest, pending: int | None = None) -> dict:
    Status = InterpreterRequest.Status
    if req.status == Status.CANCELLED:
        return {"tone": "cancelled", "label": "Cancelled"}
    if req.status == Status.CLOSED:
        tone = "closed" if req.served else "closed-muted"
        return {"tone": tone, "label": req.get_outcome_display()}
    if req.needs_outcome:
        return {"tone": "outcome", "label": "Needs outcome"}
    if req.status == Status.ASSIGNED:
        return {"tone": "assigned", "label": "Assigned"}
    if pending is None:
        pending = req.offers.filter(status=Offer.Status.PENDING).count()
    if pending:
        return {"tone": "offered", "label": f"Offered · {pending}"}
    return {"tone": "open", "label": "Unassigned"}


@register.filter
def offer_tone(status: str) -> str:
    return {
        Offer.Status.PENDING: "offered",
        Offer.Status.ACCEPTED: "assigned",
        Offer.Status.DECLINED: "cancelled",
        Offer.Status.EXPIRED: "closed-muted",
        Offer.Status.WITHDRAWN: "closed-muted",
    }.get(status, "closed")


@register.filter
def initials(name: str) -> str:
    parts = [part for part in (name or "").split() if part]
    return "".join(part[0] for part in parts[:2]).upper()


@register.filter
def hours(minutes: int | None) -> str:
    if not minutes:
        return "–"
    if minutes < 60:
        return f"{minutes} min"
    value = minutes / 60
    return f"{value:.1f} h".replace(".0 h", " h")
