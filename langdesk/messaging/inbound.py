"""Turn an inbound text into an action: accept, decline, opt out, or ask for help."""

from __future__ import annotations

import re

from django.conf import settings
from django.utils import timezone
from django.utils.formats import date_format

from langdesk.core.phone import normalize_phone
from langdesk.roster.models import Interpreter

from .models import InboundMessage, Notification
from .services import queue_sms

ACCEPT = {"yes", "y", "accept", "ok", "okay", "si", "sí", "oui", "confirm", "sure"}
DECLINE = {"no", "n", "decline", "pass", "busy"}
STOP = {"stop", "stopall", "unsubscribe", "cancel", "end", "quit"}
START = {"start", "unstop", "subscribe"}
HELP = {"help", "info"}
_WORDS = re.compile(r"[^\W_]+", re.UNICODE)

Result = InboundMessage.Result


def parse(body: str) -> tuple[str, str]:
    """Return ``(intent, code)`` where intent is accept/decline/stop/start/help/unknown."""
    words = [word.lower() for word in _WORDS.findall(body or "")]
    code = next((word for word in words if word.isdigit() and len(word) == 4), "")
    first = next((word for word in words if not word.isdigit()), "")
    for intent, keywords in (
        ("accept", ACCEPT),
        ("decline", DECLINE),
        ("stop", STOP),
        ("start", START),
        ("help", HELP),
    ):
        if first in keywords:
            return intent, code
    return "unknown", code


def _offer_line(offer) -> str:
    when = date_format(timezone.localtime(offer.request.starts_at), "D g:i A")
    return f"{offer.code} {offer.request.language} {when}"


def handle_sms(from_number: str, body: str) -> InboundMessage:
    from langdesk.scheduling.models import Offer
    from langdesk.scheduling.services.dispatch import Reply, accept_offer, decline_offer

    number = normalize_phone(from_number)
    person = Interpreter.objects.filter(phone=number).first() if number else None
    intent, code = parse(body)
    inbound = InboundMessage(
        from_address=number or from_number, body=body[:1600], interpreter=person
    )
    org = settings.LANGDESK_ORG_NAME
    reply = ""

    if person is None:
        inbound.result = Result.UNKNOWN_SENDER
    elif intent == "stop":
        person.sms_opt_out = True
        person.save(update_fields=["sms_opt_out", "updated_at"])
        inbound.result = Result.STOP
    elif intent == "start":
        person.sms_opt_out = False
        person.save(update_fields=["sms_opt_out", "updated_at"])
        inbound.result = Result.START
        reply = f"{org}: you'll get interpreting offers by text again. Reply STOP to opt out."
    elif intent == "help":
        inbound.result = Result.HELP
        reply = (
            f"{org}: reply YES 1234 to accept an offer or NO 1234 to decline, using the code "
            f"in the offer. Reply STOP to stop texts."
        )
        if settings.LANGDESK_SUPPORT_CONTACT:
            reply += f" Help: {settings.LANGDESK_SUPPORT_CONTACT}"
    elif intent in {"accept", "decline"}:
        offers = Offer.objects.filter(interpreter=person).select_related("request__language")
        if code:
            offer = offers.filter(code=code).order_by("-sent_at").first()
            candidates = [offer] if offer else []
        else:
            candidates = list(offers.pending().order_by("request__starts_at"))
        if not candidates:
            inbound.result = Result.NO_OFFER
            reply = f"{org}: we couldn't find an open offer{' with code ' + code if code else ''}."
        elif len(candidates) > 1:
            inbound.result = Result.AMBIGUOUS
            lines = "; ".join(_offer_line(o) for o in candidates[:4])
            word = "YES" if intent == "accept" else "NO"
            reply = (
                f"{org}: you have {len(candidates)} open offers ({lines}). "
                f"Reply {word} plus the code."
            )
        else:
            offer = candidates[0]
            inbound.offer = offer
            if intent == "accept":
                outcome = accept_offer(offer, channel="sms")
                if outcome == Reply.ACCEPTED:
                    inbound.result = Result.ACCEPTED
                else:
                    inbound.result = Result.ALREADY_FILLED
                    reply = (
                        f"{org}: thanks! That {offer.request.language} request is already filled."
                    )
            else:
                decline_offer(offer, channel="sms")
                inbound.result = Result.DECLINED
                reply = f"{org}: thanks for letting us know."
    else:
        inbound.result = Result.UNRECOGNISED
        reply = f"{org}: reply YES or NO with the 4-digit code from the offer, or HELP."

    inbound.reply = reply
    inbound.save()
    if reply and person and person.phone:
        queue_sms(person.phone, reply, kind=Notification.Kind.REPLY, interpreter=person)
    return inbound
