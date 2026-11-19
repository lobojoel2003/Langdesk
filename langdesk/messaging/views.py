from __future__ import annotations

import hmac
import json

from django.conf import settings
from django.contrib import messages
from django.http import Http404, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from langdesk.core.roles import coordinator_required
from langdesk.roster.models import Interpreter

from . import twilio_signature
from .inbound import handle_sms
from .models import Channel, InboundMessage, Notification

EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


@csrf_exempt
@require_POST
def twilio_inbound(request):
    """Twilio Messaging webhook. Configure it as ``{BASE_URL}/sms/twilio/`` (HTTP POST)."""
    url = f"{settings.LANGDESK_BASE_URL}{request.get_full_path()}"
    params = dict(request.POST.lists())
    signature = request.headers.get("X-Twilio-Signature", "")
    if not twilio_signature.is_valid(settings.TWILIO_AUTH_TOKEN, url, params, signature):
        return HttpResponseForbidden("Invalid Twilio signature")
    handle_sms(request.POST.get("From", ""), request.POST.get("Body", ""))
    return HttpResponse(EMPTY_TWIML, content_type="text/xml")


@csrf_exempt
@require_POST
def generic_inbound(request):
    """Provider-neutral webhook.

    POST ``{"from": "+15555550101", "body": "YES 1234"}`` (JSON or form) with
    ``Authorization: Bearer <LANGDESK_SMS_INBOUND_TOKEN>``.
    """
    expected = settings.LANGDESK_SMS_INBOUND_TOKEN
    supplied = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not expected or not hmac.compare_digest(expected, supplied):
        return HttpResponseForbidden("Invalid token")
    if request.content_type == "application/json":
        try:
            payload = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            return JsonResponse({"error": "Body must be JSON"}, status=400)
    else:
        payload = request.POST
    sender, body = payload.get("from", ""), payload.get("body", "")
    if not sender:
        return JsonResponse({"error": "'from' is required"}, status=400)
    inbound = handle_sms(sender, body)
    return JsonResponse({"result": inbound.result, "reply": inbound.reply})


@coordinator_required
def simulator(request):
    """Reply to offers as an interpreter would, without a real SMS provider."""
    if not settings.LANGDESK_SMS_SIMULATOR:
        raise Http404
    people = Interpreter.objects.active().exclude(phone="")
    person = None
    if request.GET.get("interpreter"):
        person = get_object_or_404(people, pk=request.GET["interpreter"])
    elif people:
        person = people[0]

    if request.method == "POST":
        person = get_object_or_404(people, pk=request.POST.get("interpreter"))
        body = request.POST.get("body", "").strip()
        if body:
            inbound = handle_sms(person.phone, body)
            messages.info(request, f"Langdesk read that as: {inbound.get_result_display()}.")
        return redirect(f"{request.path}?interpreter={person.pk}")

    thread = []
    if person:
        outbound = Notification.objects.filter(channel=Channel.SMS, to_address=person.phone)[:40]
        inbound = InboundMessage.objects.filter(from_address=person.phone)[:40]
        thread = sorted(
            [{"direction": "out", "at": n.created_at, "body": n.body} for n in outbound]
            + [{"direction": "in", "at": m.received_at, "body": m.body} for m in inbound],
            key=lambda item: item["at"],
        )
    return render(
        request,
        "messaging/simulator.html",
        {"people": people, "person": person, "thread": thread},
    )
