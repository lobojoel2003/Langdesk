from __future__ import annotations

import datetime as dt
from collections import OrderedDict

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.views.decorators.http import require_POST

from langdesk.core.roles import coordinator_required, is_coordinator
from langdesk.messaging.models import InboundMessage, Notification
from langdesk.roster.models import Interpreter, InterpreterLanguage, Language

from . import ics
from .forms import InterpreterChoiceForm, OutcomeForm, ReasonForm, RequestForm
from .models import InterpreterRequest, Offer
from .services import dispatch
from .services.matching import match
from .services.notify import absolute

Status = InterpreterRequest.Status


def _requests():
    return InterpreterRequest.objects.select_related(
        "language", "location", "department", "interpreter", "requested_by"
    )


def _get_request(request, pk: int) -> InterpreterRequest:
    return get_object_or_404(_requests().visible_to(request.user), pk=pk)


def _can_manage(user, req: InterpreterRequest) -> bool:
    return is_coordinator(user) or req.requested_by_id == user.pk


def _frequent_languages(limit: int = 8):
    since = timezone.now() - dt.timedelta(days=90)
    return list(
        Language.objects.filter(is_active=True)
        .annotate(recent=Count("requests", filter=Q(requests__created_at__gte=since)))
        .filter(recent__gt=0)
        .order_by("-recent", "name")[:limit]
    )


@login_required
def home(request):
    if is_coordinator(request.user):
        return redirect("scheduling:board")
    return redirect("scheduling:list")


@login_required
def request_new(request):
    form = RequestForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        req = dispatch.create_request(form.save(commit=False), request.user)
        if req.offers.exists():
            note = (
                f"offered to {req.offers.count()} interpreter(s). "
                "You'll get an email once one accepts."
            )
        else:
            note = "the language access team will assign an interpreter."
        messages.success(request, f"{req.reference} requested: {note}")
        return redirect(req)
    return render(
        request,
        "scheduling/request_form.html",
        {"form": form, "frequent": _frequent_languages(), "creating": True},
    )


@login_required
def request_edit(request, pk: int):
    req = _get_request(request, pk)
    if not req.is_active or not _can_manage(request.user, req):
        raise PermissionDenied
    form = RequestForm(request.POST or None, instance=req, user=request.user)
    if request.method == "POST" and form.is_valid():
        changed = form.changed_fields
        req = form.save()
        dispatch.update_request(req, changed, request.user)
        messages.success(request, f"{req.reference} updated.")
        return redirect(req)
    return render(
        request,
        "scheduling/request_form.html",
        {"form": form, "frequent": _frequent_languages(), "req": req, "creating": False},
    )


FILTERS = OrderedDict(
    [
        ("active", ("Upcoming", Q(status__in=[Status.OPEN, Status.ASSIGNED]))),
        ("open", ("Unassigned", Q(status=Status.OPEN))),
        ("outcome", ("Needs outcome", None)),
        ("closed", ("Closed", Q(status=Status.CLOSED))),
        ("cancelled", ("Cancelled", Q(status=Status.CANCELLED))),
        ("all", ("All", Q())),
    ]
)


@login_required
def request_list(request):
    view = request.GET.get("view", "active")
    if view not in FILTERS:
        view = "active"
    qs = _requests().visible_to(request.user)
    if view == "outcome":
        qs = qs.needs_outcome()
    else:
        condition = FILTERS[view][1]
        qs = qs.filter(condition)
        if view == "active":
            qs = qs.filter(ends_at__gt=timezone.now())
    query = request.GET.get("q", "").strip()
    if query:
        qs = qs.filter(
            Q(reference__icontains=query)
            | Q(appointment_ref__icontains=query)
            | Q(language__name__icontains=query)
        )
    if view in {"closed", "cancelled", "all"}:
        qs = qs.order_by("-starts_at")
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "scheduling/request_list.html",
        {
            "page": page,
            "view": view,
            "filters": [(key, label) for key, (label, _) in FILTERS.items()],
            "query": query,
            "mine": not is_coordinator(request.user),
        },
    )


@login_required
def request_detail(request, pk: int):
    req = _get_request(request, pk)
    coordinator = is_coordinator(request.user)
    context = {
        "req": req,
        "can_manage": _can_manage(request.user, req),
        "events": req.events.select_related("actor", "interpreter"),
        "offers": req.offers.select_related("interpreter").order_by("-sent_at"),
    }
    if coordinator and req.is_active:
        context["match"] = match(req)
        context["others"] = (
            Interpreter.objects.active()
            .filter(languages=req.language)
            .exclude(pk=req.interpreter_id or 0)
        )
    if coordinator:
        context["notifications"] = req.notifications.order_by("-created_at")[:50]
    if req.is_active and req.has_started:
        context["outcome_form"] = OutcomeForm(req=req)
    return render(request, "scheduling/request_detail.html", context)


def _post_action(request, pk: int, *, coordinator_only: bool = True) -> InterpreterRequest:
    req = _get_request(request, pk)
    allowed = is_coordinator(request.user) if coordinator_only else _can_manage(request.user, req)
    if not allowed:
        raise PermissionDenied
    return req


def _run(request, req, action, success: str):
    try:
        action()
    except dispatch.DispatchError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, success)
    return redirect(request.POST.get("next") or req.get_absolute_url())


@require_POST
@login_required
def request_offer(request, pk: int):
    req = _post_action(request, pk)
    form = InterpreterChoiceForm(request.POST)
    if form.is_valid():
        person = form.cleaned_data["interpreter"]
        return _run(
            request,
            req,
            lambda: dispatch.offer_to(req, person, request.user),
            f"Offer sent to {person}.",
        )
    sent: list[Offer] = []

    def wave():
        sent.extend(dispatch.send_offer_wave(req, actor=request.user))
        if not sent:
            raise dispatch.DispatchError("Nobody else is available to offer this to.")

    return _run(request, req, wave, "Offers sent.")


@require_POST
@login_required
def request_assign(request, pk: int):
    req = _post_action(request, pk)
    form = InterpreterChoiceForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Choose an interpreter.")
        return redirect(req)
    person = form.cleaned_data["interpreter"]
    return _run(
        request, req, lambda: dispatch.assign(req, person, request.user), f"{person} assigned."
    )


@require_POST
@login_required
def request_unassign(request, pk: int):
    req = _post_action(request, pk)
    form = ReasonForm(request.POST)
    reason = form.cleaned_data["reason"] if form.is_valid() else ""
    return _run(
        request,
        req,
        lambda: dispatch.unassign(req, request.user, reason),
        "Interpreter released. Langdesk is offering it to the next people in line.",
    )


@require_POST
@login_required
def request_video(request, pk: int):
    req = _post_action(request, pk, coordinator_only=False)

    def switch():
        if not dispatch.fall_back_to_video(req, actor=request.user):
            raise dispatch.DispatchError("Only unassigned in-person requests can switch to video.")

    return _run(request, req, switch, "Switched to video. The link is on this page.")


@require_POST
@login_required
def request_cancel(request, pk: int):
    req = _post_action(request, pk, coordinator_only=False)
    form = ReasonForm(request.POST)
    reason = form.cleaned_data["reason"] if form.is_valid() else ""
    return _run(
        request,
        req,
        lambda: dispatch.cancel(req, request.user, reason),
        f"{req.reference} cancelled.",
    )


@require_POST
@login_required
def request_outcome(request, pk: int):
    req = _post_action(request, pk, coordinator_only=False)
    form = OutcomeForm(request.POST, req=req)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect(req)
    data = form.cleaned_data
    return _run(
        request,
        req,
        lambda: dispatch.record_outcome(
            req,
            outcome=data["outcome"],
            actual_minutes=data["actual_minutes"],
            notes=data["notes"],
            actor=request.user,
        ),
        "Outcome recorded.",
    )


@login_required
def request_ics(request, pk: int):
    req = _get_request(request, pk)
    response = HttpResponse(ics.single(req), content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{req.reference}.ics"'
    return response


# --- Coordinator board ------------------------------------------------------


def _day_label(day: dt.date, today: dt.date) -> str:
    if day == today:
        return "Today"
    if day == today + dt.timedelta(days=1):
        return "Tomorrow"
    return date_format(day, "l, F j")


@coordinator_required
def board(request):
    now = timezone.now()
    today = timezone.localdate()
    offers = Prefetch(
        "offers", queryset=Offer.objects.select_related("interpreter").order_by("-score")
    )
    open_requests = list(
        _requests().open().filter(ends_at__gt=now).prefetch_related(offers).order_by("starts_at")
    )
    days: OrderedDict[str, list] = OrderedDict()
    for req in open_requests:
        found = match(req)
        card = {
            "req": req,
            "top": found.candidates[:3],
            "fresh": len(found.fresh(settings.LANGDESK_OFFER_WAVE_SIZE)),
            "more": max(0, len(found.candidates) - 3),
            "pending": [o for o in req.offers.all() if o.status == Offer.Status.PENDING],
        }
        label = _day_label(timezone.localtime(req.starts_at).date(), today)
        days.setdefault(label, []).append(card)

    day_start = timezone.make_aware(dt.datetime.combine(today, dt.time.min))
    assigned = (
        _requests()
        .assigned()
        .filter(ends_at__gt=now, starts_at__lt=day_start + dt.timedelta(days=2))
    )
    needs_outcome = _requests().needs_outcome(now).order_by("-ends_at")
    stats = {
        "open": len(open_requests),
        "urgent": sum(1 for r in open_requests if r.starts_at - now < dt.timedelta(hours=24)),
        "pending": Offer.objects.pending().filter(request__status=Status.OPEN).count(),
        "assigned_today": _requests()
        .filter(
            status__in=[Status.ASSIGNED, Status.CLOSED],
            starts_at__gte=day_start,
            starts_at__lt=day_start + dt.timedelta(days=1),
        )
        .count(),
        "needs_outcome": needs_outcome.count(),
    }
    return render(
        request,
        "scheduling/board.html",
        {
            "days": days,
            "assigned": assigned,
            "needs_outcome": needs_outcome[:12],
            "stats": stats,
            "now": now,
        },
    )


# --- Interpreters -----------------------------------------------------------


@coordinator_required
def interpreter_list(request):
    week_end = timezone.now() + dt.timedelta(days=7)
    skills = Prefetch(
        "language_skills", queryset=InterpreterLanguage.objects.select_related("language")
    )
    interpreters = (
        Interpreter.objects.active()
        .select_related("home_location")
        .prefetch_related(skills)
        .annotate(
            upcoming=Count(
                "assignments",
                filter=Q(
                    assignments__status=Status.ASSIGNED,
                    assignments__starts_at__gte=timezone.now(),
                    assignments__starts_at__lt=week_end,
                ),
            )
        )
        .order_by("name")
    )
    language = request.GET.get("language")
    if language:
        interpreters = interpreters.filter(languages__code=language)
    return render(
        request,
        "scheduling/interpreter_list.html",
        {
            "interpreters": interpreters,
            "languages": Language.objects.filter(is_active=True, skills__isnull=False).distinct(),
            "language": language,
        },
    )


@coordinator_required
def interpreter_detail(request, pk: int):
    person = get_object_or_404(
        Interpreter.objects.select_related("home_location").prefetch_related(
            "language_skills__language", "availability", "serves_locations"
        ),
        pk=pk,
    )
    if request.method == "POST" and request.POST.get("action") == "rotate":
        person.rotate_feed_token()
        messages.success(request, "New calendar link issued. The old link no longer works.")
        return redirect("scheduling:interpreter", pk=person.pk)
    now = timezone.now()
    year_start = timezone.make_aware(dt.datetime(timezone.localdate().year, 1, 1))
    offers = person.offers.exclude(status=Offer.Status.PENDING)
    answered = offers.count()
    accepted = offers.filter(status=Offer.Status.ACCEPTED).count()
    closed = person.assignments.filter(
        status=Status.CLOSED,
        starts_at__gte=year_start,
        outcome__in=InterpreterRequest.SERVED_OUTCOMES,
    )
    minutes = sum(r.billable_minutes for r in closed.only("actual_minutes", "starts_at", "ends_at"))
    return render(
        request,
        "scheduling/interpreter_detail.html",
        {
            "person": person,
            "upcoming": _requests().filter(
                interpreter=person, status=Status.ASSIGNED, ends_at__gt=now
            ),
            "pending": person.offers.pending().select_related("request__language"),
            "recent": _requests()
            .filter(interpreter=person, status=Status.CLOSED)
            .order_by("-starts_at")[:10],
            "feed_url": absolute(reverse("scheduling:feed", args=[person.feed_token])),
            "acceptance": round(100 * accepted / answered) if answered else None,
            "answered": answered,
            "jobs_this_year": closed.count(),
            "hours_this_year": round(minutes / 60, 1),
            "inbound": InboundMessage.objects.filter(interpreter=person)[:10],
            "outbound": Notification.objects.filter(interpreter=person)[:10],
        },
    )


# --- Public endpoints (no login) -------------------------------------------


def offer_respond(request, token: str):
    """The link in offer texts and emails. GET only shows; POST changes state."""
    offer = get_object_or_404(
        Offer.objects.select_related(
            "interpreter", "request__language", "request__location", "request__department"
        ),
        token=token,
    )
    result = None
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "accept":
            result = dispatch.accept_offer(offer, channel="web")
        elif action == "decline":
            result = dispatch.decline_offer(offer, channel="web")
        offer.refresh_from_db()
        offer.request.refresh_from_db()
    req = offer.request
    can_respond = (
        req.status == Status.OPEN
        and req.ends_at > timezone.now()
        and offer.status in {Offer.Status.PENDING, Offer.Status.EXPIRED}
    )
    return render(
        request,
        "scheduling/offer_respond.html",
        {"offer": offer, "req": req, "result": result, "can_respond": can_respond},
    )


def calendar_feed(request, token: str):
    person = get_object_or_404(Interpreter, feed_token=token, is_active=True)
    response = HttpResponse(ics.feed(person), content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = 'inline; filename="langdesk.ics"'
    response["Cache-Control"] = "private, max-age=300"
    return response
