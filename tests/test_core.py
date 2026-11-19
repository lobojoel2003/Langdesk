import datetime as dt
from io import StringIO
from unittest import mock

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.management import call_command
from django.db import DatabaseError
from django.template import Context, Template
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from langdesk import version
from langdesk.core import views as core_views
from langdesk.core.phone import normalize_phone, validate_phone
from langdesk.core.roles import is_coordinator
from langdesk.core.templatetags import langdesk as tags
from langdesk.roster.models import AvailabilityWindow, Interpreter, InterpreterLanguage, TimeOff
from langdesk.scheduling.models import InterpreterRequest, Offer
from langdesk.scheduling.tasks import expire_stale_offers, run_dispatcher

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("(555) 555-0101", "+15555550101"),
        ("1 555 555 0101", "+15555550101"),
        ("+44 20 7946 0958", "+442079460958"),
        ("0044 20 7946 0958", "+442079460958"),
        ("", ""),
        (None, ""),
        ("abc", ""),
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


def test_validate_phone():
    validate_phone("555 555 0101")
    with pytest.raises(ValidationError):
        validate_phone("12")


def test_interpreter_validation(make_interpreter):
    person = Interpreter(name="Nobody")
    with pytest.raises(ValidationError, match="mobile number or an email"):
        person.clean()
    agency = Interpreter(name="Agency", email="a@example.org", employment="agency")
    with pytest.raises(ValidationError):
        agency.clean()
    window = AvailabilityWindow(weekday=0, start_time=dt.time(10), end_time=dt.time(9))
    with pytest.raises(ValidationError):
        window.clean()
    now = timezone.now()
    with pytest.raises(ValidationError):
        TimeOff(starts_at=now, ends_at=now).clean()
    assert str(window) == "Monday 10:00-09:00"


def test_availability_window_covers_same_day_only():
    window = AvailabilityWindow(weekday=0, start_time=dt.time(8), end_time=dt.time(17))
    monday = timezone.make_aware(dt.datetime(2026, 11, 16, 9))
    assert window.covers(monday, monday + dt.timedelta(hours=2))
    assert not window.covers(monday, monday + dt.timedelta(hours=9))
    assert not window.covers(monday + dt.timedelta(days=1), monday + dt.timedelta(days=1, hours=1))


def test_model_strings(make_interpreter, make_request, spanish, clinic):
    person = make_interpreter("Ana")
    skill = person.language_skills.get()
    req = make_request()
    offer = Offer.objects.create(
        request=req, interpreter=person, code="1234", expires_at=timezone.now()
    )
    assert str(skill) == "Ana - Spanish (Qualified)"
    assert str(spanish) == "Spanish" and str(clinic) == "Main Clinic"
    assert str(req).startswith(f"{req.reference} · Spanish")
    assert str(offer) == f"Offer 1234 to Ana for {req.reference}"
    assert str(InterpreterRequest(language=spanish, starts_at=timezone.now())).startswith(
        "New request"
    )
    assert skill.effective_credential == InterpreterLanguage.Credential.QUALIFIED


def test_roles(coordinator, requester, admin_user, rf):
    assert is_coordinator(coordinator) and is_coordinator(admin_user)
    assert not is_coordinator(requester)
    assert not is_coordinator(None)
    assert Group.objects.filter(name="Coordinators").exists()
    assert (
        Group.objects.get(name="Coordinators")
        .permissions.filter(codename="change_interpreter")
        .exists()
    )


def test_healthz(client):
    response = client.get(reverse("healthz"))
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["version"] == version.__version__


def test_healthz_reports_database_trouble(rf):
    with mock.patch.object(core_views.connection, "cursor", side_effect=DatabaseError):
        response = core_views.healthz(rf.get("/healthz"))
    assert response.status_code == 503


def test_build_info(monkeypatch):
    monkeypatch.setenv("LANGDESK_BUILD_NUMBER", "42")
    monkeypatch.setenv("LANGDESK_GIT_SHA", "abcdef1234567")
    info = version.build_info()
    assert info == {
        "version": version.__version__,
        "build": "42",
        "commit": "abcdef1",
        "built_at": "",
    }


def test_version_is_semver():
    major, minor, patch = version.__version__.split(".")
    assert all(part.isdigit() for part in (major, minor, patch))


def test_footer_shows_version(requester_client):
    body = requester_client.get(reverse("scheduling:list")).content.decode()
    assert f"Langdesk v{version.__version__}" in body


def test_error_pages(requester_client):
    request = RequestFactory().get("/missing")
    request.user = mock.Mock(is_authenticated=False)
    assert core_views.handler404(request, None).status_code == 404
    assert core_views.handler403(request, None).status_code == 403
    assert core_views.handler500(request).status_code == 500
    assert requester_client.get("/does-not-exist/").status_code == 404


def test_template_helpers(make_request):
    now = timezone.now()
    assert tags.until(now + dt.timedelta(minutes=30, seconds=5)) == "in 30 min"
    assert tags.until(now + dt.timedelta(hours=5, minutes=1)) == "in 5 h"
    assert tags.until(now + dt.timedelta(days=3, minutes=1)) == "in 3 days"
    assert tags.until(now - dt.timedelta(minutes=12, seconds=5)) == "12 min ago"
    assert tags.until(now) == "now"
    assert tags.hours(None) == "–"
    assert tags.hours(45) == "45 min"
    assert tags.hours(60) == "1 h"
    assert tags.hours(90) == "1.5 h"
    assert tags.initials("ana maria") == "AM"
    assert tags.modality_label("video") == "Video"
    assert tags.offer_tone("declined") == "cancelled"
    assert 'aria-label="Video"' in tags.icon("video", label="Video")
    assert "<svg" in tags.icon("unknown")
    req = make_request()
    html = Template("{% load langdesk %}{% status_pill req %}").render(Context({"req": req}))
    assert "Unassigned" in html


@pytest.mark.parametrize(
    ("fields", "label"),
    [
        ({"status": "cancelled"}, "Cancelled"),
        ({"status": "closed", "outcome": "completed"}, "Interpreted"),
        ({"status": "closed", "outcome": "unfilled"}, "No interpreter found"),
        ({"status": "assigned"}, "Assigned"),
    ],
)
def test_status_pill(make_request, fields, label):
    assert tags.status_pill(make_request(**fields))["label"] == label


def test_status_pill_needs_outcome_and_offered(make_request, make_interpreter):
    past = make_request(starts_in=dt.timedelta(hours=-3))
    assert tags.status_pill(past)["label"] == "Needs outcome"
    req = make_request()
    Offer.objects.create(
        request=req, interpreter=make_interpreter("A"), code="1", expires_at=timezone.now()
    )
    assert tags.status_pill(req)["label"] == "Offered · 1"


def test_settings_require_secret_key_in_production(monkeypatch):
    import importlib

    import langdesk.settings as settings_module

    monkeypatch.setenv("DJANGO_SECRET_KEY", "")
    monkeypatch.setenv("DJANGO_DEBUG", "false")
    with pytest.raises(ImproperlyConfigured):
        importlib.reload(settings_module)
    monkeypatch.setenv("DJANGO_DEBUG", "true")
    reloaded = importlib.reload(settings_module)
    assert reloaded.SECRET_KEY.startswith("django-insecure")
    monkeypatch.setenv("LANGDESK_OFFER_WAVE_SIZE", "lots")
    with pytest.raises(ImproperlyConfigured):
        importlib.reload(settings_module)
    monkeypatch.setenv("LANGDESK_OFFER_WAVE_SIZE", "")
    monkeypatch.setenv("DJANGO_SECRET_KEY", "x")
    assert importlib.reload(settings_module).LANGDESK_OFFER_WAVE_SIZE == 3


def test_celery_tasks(make_request, make_interpreter):
    person = make_interpreter("Ana")
    req = make_request(status=InterpreterRequest.Status.CANCELLED)
    Offer.objects.create(request=req, interpreter=person, code="1", expires_at=timezone.now())
    old = make_request(starts_in=dt.timedelta(days=-2))
    Offer.objects.create(request=old, interpreter=person, code="2", expires_at=timezone.now())
    assert expire_stale_offers() == 2
    assert set(run_dispatcher()) == {"expired", "fallbacks", "waves", "reminders"}


def test_run_dispatcher_command():
    out = StringIO()
    call_command("run_dispatcher", stdout=out)
    assert "expired=0" in out.getvalue()


def test_run_dispatcher_loop_stops_on_interrupt():
    out = StringIO()
    with mock.patch("time.sleep", side_effect=KeyboardInterrupt), pytest.raises(KeyboardInterrupt):
        call_command("run_dispatcher", loop=True, interval=1, stdout=out)
    assert "reminders=0" in out.getvalue()


def test_seed_demo(settings):
    out = StringIO()
    call_command("seed_demo", history=40, stdout=out)
    assert "Demo data loaded" in out.getvalue()
    assert InterpreterRequest.objects.filter(status="open").exists()
    assert InterpreterRequest.objects.filter(status="closed").count() > 20
    with pytest.raises(Exception, match="already exist"):
        call_command("seed_demo", stdout=out)


def test_admin_pages(admin_client, make_interpreter, make_request):
    person = make_interpreter("Ana")
    req = make_request(status="assigned", interpreter=person)
    for url in [
        reverse("admin:roster_interpreter_changelist"),
        reverse("admin:roster_interpreter_change", args=[person.pk]),
        reverse("admin:roster_interpreter_add"),
        reverse("admin:roster_language_changelist"),
        reverse("admin:roster_location_changelist"),
        reverse("admin:roster_department_changelist"),
        reverse("admin:scheduling_interpreterrequest_changelist"),
        reverse("admin:scheduling_interpreterrequest_change", args=[req.pk]),
        reverse("admin:scheduling_requestevent_changelist"),
    ]:
        assert admin_client.get(url).status_code == 200, url
    old = person.feed_token
    admin_client.post(
        reverse("admin:roster_interpreter_changelist"),
        {"action": "rotate_feed_tokens", "_selected_action": [person.pk]},
    )
    person.refresh_from_db()
    assert person.feed_token != old
    admin_client.post(
        reverse("admin:roster_interpreter_changelist"),
        {"action": "deactivate", "_selected_action": [person.pk]},
    )
    person.refresh_from_db()
    assert not person.is_active
