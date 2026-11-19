import pytest
from django.urls import reverse
from icalendar import Calendar

from langdesk.roster.models import Interpreter
from langdesk.scheduling import ics
from langdesk.scheduling.models import InterpreterRequest, Modality

pytestmark = pytest.mark.django_db


@pytest.fixture
def assigned(make_interpreter, make_request, department):
    person = make_interpreter("Ana Ramirez")
    req = make_request(
        status=InterpreterRequest.Status.ASSIGNED,
        interpreter=person,
        appointment_ref="APPT-1",
        notes="Check in at desk",
        location_detail="Room 3",
        department=department,
        sequence=2,
    )
    return req, person


@pytest.fixture
def department(db):
    from langdesk.roster.models import Department

    return Department.objects.create(name="Pediatrics")


def parse(text) -> Calendar:
    return Calendar.from_ical(text)


def test_invite_is_an_itip_request(assigned):
    req, person = assigned
    cal = parse(ics.invite(req, person))
    event = cal.walk("VEVENT")[0]
    assert cal["METHOD"] == "REQUEST"
    assert str(event["UID"]) == f"request-{req.pk}@langdesk.test"
    assert event["SEQUENCE"] == 2
    assert str(event["STATUS"]) == "CONFIRMED"
    assert str(event["SUMMARY"]) == f"Interpreting: Spanish · {req.reference}"
    assert "Main Clinic, Room 3, 1 Main St" in str(event["LOCATION"])
    description = str(event["DESCRIPTION"])
    for text in [
        "Appointment: APPT-1",
        "Department: Pediatrics",
        "Arrival: Front desk",
        "Notes: Check",
    ]:
        assert text in description
    assert str(event["ATTENDEE"]) == f"mailto:{person.email}"
    assert event.walk("VALARM")


def test_cancel_invite(assigned):
    req, person = assigned
    cal = parse(ics.invite(req, person, cancelled=True))
    assert cal["METHOD"] == "CANCEL"
    assert str(cal.walk("VEVENT")[0]["STATUS"]) == "CANCELLED"
    assert not cal.walk("VALARM")


def test_video_and_phone_locations(make_request, make_interpreter):
    person = make_interpreter("No Email", email="")
    video = make_request(modality=Modality.VIDEO, video_url="https://meet.jit.si/x")
    phone = make_request(modality=Modality.PHONE, location=None)
    assert str(parse(ics.invite(video, person)).walk("VEVENT")[0]["LOCATION"]) == (
        "https://meet.jit.si/x"
    )
    event = parse(ics.invite(phone, person)).walk("VEVENT")[0]
    assert str(event["LOCATION"]) == "Phone call"
    assert "ATTENDEE" not in event
    assert video.place == "Video call" and phone.place == "Phone call"


def test_feed_lists_current_assignments_only(assigned, make_request):
    req, person = assigned
    make_request(
        status=InterpreterRequest.Status.CANCELLED, interpreter=person, outcome="cancelled"
    )
    cal = parse(ics.feed(person))
    assert [str(e["UID"]) for e in cal.walk("VEVENT")] == [ics.uid_for(req)]
    assert str(cal["X-WR-CALNAME"]) == "Test Clinic · Ana Ramirez"


def test_feed_view_is_public_but_token_protected(client, assigned):
    _, person = assigned
    url = reverse("scheduling:feed", args=[person.feed_token])
    response = client.get(url)
    assert response.status_code == 200
    assert response["Content-Type"] == "text/calendar; charset=utf-8"
    assert b"BEGIN:VCALENDAR" in response.content
    assert client.get(reverse("scheduling:feed", args=["nope"])).status_code == 404
    Interpreter.objects.filter(pk=person.pk).update(is_active=False)
    assert client.get(url).status_code == 404


def test_request_download(coordinator_client, assigned):
    req, _ = assigned
    response = coordinator_client.get(reverse("scheduling:ics", args=[req.pk]))
    assert response.status_code == 200
    assert f'filename="{req.reference}.ics"' in response["Content-Disposition"]
    assert parse(response.content)["METHOD"] == "PUBLISH"
