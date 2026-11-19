import datetime as dt

import pytest
from django.urls import reverse
from django.utils import timezone

from langdesk.roster.models import Department
from langdesk.scheduling.models import InterpreterRequest, Modality, Offer
from langdesk.scheduling.services import dispatch

from .conftest import at_local

pytestmark = pytest.mark.django_db
Status = InterpreterRequest.Status


def form_data(spanish, clinic, **overrides):
    start = at_local(3, 10)
    data = {
        "language": spanish.pk,
        "date": start.date().isoformat(),
        "start_time": "10:00",
        "duration": 60,
        "modality": Modality.IN_PERSON,
        "location": clinic.pk,
        "location_detail": "Room 3",
        "service_type": "medical",
        "department": "",
        "appointment_ref": "APPT-48213",
        "notes": "",
    }
    data.update(overrides)
    return data


# --- Access -----------------------------------------------------------------


def test_login_required(client):
    for name in ["home", "scheduling:new", "scheduling:list", "scheduling:board"]:
        response = client.get(reverse(name))
        assert response.status_code == 302
        assert response["Location"].startswith(reverse("login"))


def test_login_page_and_sign_in(client, requester):
    assert client.get(reverse("login")).status_code == 200
    response = client.post(reverse("login"), {"username": "nurse", "password": "pw"})
    assert response.status_code == 302
    assert client.get(reverse("home"))["Location"] == reverse("scheduling:list")


def test_coordinators_land_on_the_board(coordinator_client):
    assert coordinator_client.get(reverse("home"))["Location"] == reverse("scheduling:board")


def test_requesters_cannot_open_coordinator_pages(requester_client, make_interpreter):
    person = make_interpreter("Ana")
    for url in [
        reverse("scheduling:board"),
        reverse("scheduling:interpreters"),
        reverse("scheduling:interpreter", args=[person.pk]),
        reverse("reports:report"),
    ]:
        assert requester_client.get(url).status_code == 302


def test_requesters_only_see_their_own_requests(requester_client, make_request, make_user):
    mine = make_request(appointment_ref="MINE-1")
    theirs = make_request(requested_by=make_user("other"), appointment_ref="THEIRS-1")
    listing = requester_client.get(reverse("scheduling:list")).content.decode()
    assert "MINE-1" in listing and "THEIRS-1" not in listing
    assert requester_client.get(mine.get_absolute_url()).status_code == 200
    assert requester_client.get(theirs.get_absolute_url()).status_code == 404
    assert requester_client.post(reverse("scheduling:cancel", args=[theirs.pk])).status_code == 404


def test_requesters_cannot_run_coordinator_actions(
    requester_client, make_request, make_interpreter
):
    req = make_request()
    person = make_interpreter("Ana")
    for name in ["offer", "assign", "unassign"]:
        response = requester_client.post(
            reverse(f"scheduling:{name}", args=[req.pk]), {"interpreter": person.pk}
        )
        assert response.status_code == 403


# --- Requesting -------------------------------------------------------------


def test_new_request_form_prefills_from_last_request(requester_client, make_request, school):
    department = Department.objects.create(name="Pediatrics")
    make_request(location=school, department=department, service_type="education")
    form = requester_client.get(reverse("scheduling:new")).context["form"]
    assert form.initial["location"] == school.pk
    assert form.initial["department"] == department.pk
    assert form.initial["service_type"] == "education"


def test_create_request(requester_client, requester, spanish, clinic, make_interpreter):
    make_interpreter("Ana")
    response = requester_client.post(reverse("scheduling:new"), form_data(spanish, clinic))
    req = InterpreterRequest.objects.get()
    assert response["Location"] == req.get_absolute_url()
    assert req.requested_by == requester
    assert req.duration_minutes == 60
    assert timezone.localtime(req.starts_at).hour == 10
    assert req.offers.count() == 1
    page = requester_client.get(response["Location"]).content.decode()
    assert "offered to 1 interpreter" in page
    assert "Most requested" in requester_client.get(reverse("scheduling:new")).content.decode()


def test_create_request_without_interpreters(requester_client, spanish, clinic):
    response = requester_client.post(
        reverse("scheduling:new"), form_data(spanish, clinic), follow=True
    )
    assert "language access team will assign" in response.content.decode()


@pytest.mark.parametrize(
    ("overrides", "field", "message"),
    [
        ({"location": ""}, "location", "Choose where the interpreter should go"),
        ({"appointment_ref": "Maria Lopez"}, "appointment_ref", "no spaces"),
        ({"notes": "DOB 04/12/1980"}, "notes", "date of birth"),
        ({"notes": "Call her at 555-123-4567"}, "notes", "phone number"),
        ({"notes": "Diagnosis: diabetes"}, "notes", "client details"),
        ({"location_detail": "jane@example.org"}, "location_detail", "email address"),
        ({"date": "2020-01-01"}, "start_time", "already passed"),
    ],
)
def test_request_validation(requester_client, spanish, clinic, overrides, field, message):
    response = requester_client.post(
        reverse("scheduling:new"), form_data(spanish, clinic, **overrides)
    )
    assert response.status_code == 200
    assert message in " ".join(response.context["form"].errors[field])
    assert not InterpreterRequest.objects.exists()


def test_sign_languages_cannot_be_by_phone(requester_client, asl, clinic):
    response = requester_client.post(
        reverse("scheduling:new"), form_data(asl, clinic, modality=Modality.PHONE)
    )
    assert "can't be interpreted by phone" in response.context["form"].errors["modality"][0]


def test_video_requests_do_not_need_a_site(requester_client, spanish, clinic):
    requester_client.post(
        reverse("scheduling:new"), form_data(spanish, clinic, modality=Modality.VIDEO, location="")
    )
    req = InterpreterRequest.objects.get()
    assert req.video_url
    assert req.place == "Video call"


def test_edit_request(requester_client, make_request, spanish, clinic, make_interpreter, sms):
    person = make_interpreter("Ana")
    req = make_request(status=Status.ASSIGNED, interpreter=person)
    page = requester_client.get(reverse("scheduling:edit", args=[req.pk]))
    assert page.context["form"].initial["duration"] == 60
    start = timezone.localtime(req.starts_at)
    data = form_data(
        spanish,
        clinic,
        date=start.date().isoformat(),
        start_time=(start + dt.timedelta(hours=1)).strftime("%H:%M"),
        duration=90,
    )
    response = requester_client.post(reverse("scheduling:edit", args=[req.pk]), data)
    assert response.status_code == 302
    req.refresh_from_db()
    assert req.duration_minutes == 90
    assert req.events.filter(kind="updated").exists()
    assert sms and "UPDATED" in sms[-1].body


def test_edit_keeps_unusual_durations(requester_client, make_request):
    req = make_request(minutes=50)
    form = requester_client.get(reverse("scheduling:edit", args=[req.pk])).context["form"]
    assert (50, "50 min") in form.fields["duration"].choices


def test_closed_requests_cannot_be_edited(requester_client, make_request):
    req = make_request(status=Status.CLOSED, outcome="completed")
    assert requester_client.get(reverse("scheduling:edit", args=[req.pk])).status_code == 403


def test_request_list_filters(coordinator_client, make_request, make_interpreter):
    person = make_interpreter("Ana")
    make_request(appointment_ref="OPEN-1")
    make_request(
        starts_at=at_local(-3, 9),
        status=Status.ASSIGNED,
        interpreter=person,
        appointment_ref="DUE-1",
    )
    make_request(
        starts_at=at_local(-5, 9),
        status=Status.CLOSED,
        outcome="completed",
        appointment_ref="DONE-1",
    )
    url = reverse("scheduling:list")

    def refs(**params):
        page = coordinator_client.get(url, params)
        return {r.appointment_ref for r in page.context["page"].object_list}

    assert refs() == {"OPEN-1"}
    assert refs(view="open") == {"OPEN-1"}
    assert refs(view="outcome") == {"DUE-1"}
    assert refs(view="closed") == {"DONE-1"}
    assert refs(view="all") == {"OPEN-1", "DUE-1", "DONE-1"}
    assert refs(view="all", q="due") == {"DUE-1"}
    assert refs(view="bogus") == {"OPEN-1"}
    assert refs(view="cancelled") == set()


# --- Coordinator actions ----------------------------------------------------


@pytest.fixture
def staffed(make_interpreter, make_request, clinic):
    ana = make_interpreter("Ana Ramirez", languages=[("es", "certified")], home_location=clinic)
    luis = make_interpreter("Luis Moreno", employment="contractor")
    return make_request(), ana, luis


def test_board_shows_ranked_candidates(coordinator_client, staffed, make_request, make_interpreter):
    req, ana, luis = staffed
    make_request(starts_in=dt.timedelta(hours=2), appointment_ref="URGENT-1")
    make_request(starts_at=at_local(-1, 9), status=Status.ASSIGNED, interpreter=luis)
    dispatch.assign(make_request(starts_in=dt.timedelta(hours=5)), ana, None)
    response = coordinator_client.get(reverse("scheduling:board"))
    assert response.status_code == 200
    body = response.content.decode()
    assert "Ana Ramirez" in body and "Same site" in body
    assert response.context["stats"]["open"] == 2
    assert response.context["stats"]["urgent"] == 1
    assert response.context["stats"]["needs_outcome"] == 1
    assert len(response.context["assigned"]) == 1


def test_empty_board(coordinator_client):
    response = coordinator_client.get(reverse("scheduling:board"))
    assert "Every request is covered" in response.content.decode()


def test_detail_page_for_coordinators(coordinator_client, staffed, make_interpreter):
    req, *_ = staffed
    make_interpreter("Remote", offers_in_person=False)
    dispatch.send_offer_wave(req)
    response = coordinator_client.get(req.get_absolute_url())
    body = response.content.decode()
    assert "Ranked interpreters" in body
    assert "Not available (1)" in body
    assert "Messages" in body
    assert len(response.context["match"].candidates) == 2


def test_offer_assign_unassign_flow(coordinator_client, staffed):
    req, ana, luis = staffed
    offer_url = reverse("scheduling:offer", args=[req.pk])

    response = coordinator_client.post(offer_url, {"interpreter": luis.pk}, follow=True)
    assert "Offer sent to Luis Moreno" in response.content.decode()
    response = coordinator_client.post(offer_url, {"interpreter": luis.pk}, follow=True)
    assert "already has this offer" in response.content.decode()

    coordinator_client.post(offer_url)  # next wave goes to Ana
    assert req.offers.filter(status=Offer.Status.PENDING).count() == 2
    response = coordinator_client.post(offer_url, follow=True)
    assert "Nobody else is available" in response.content.decode()

    response = coordinator_client.post(
        reverse("scheduling:assign", args=[req.pk]), {"interpreter": ana.pk}, follow=True
    )
    assert "Ana Ramirez assigned" in response.content.decode()
    req.refresh_from_db()
    assert req.interpreter == ana
    assert coordinator_client.get(req.get_absolute_url()).status_code == 200

    response = coordinator_client.post(
        reverse("scheduling:unassign", args=[req.pk]), {"reason": "Sick"}
    )
    req.refresh_from_db()
    assert req.status == Status.OPEN
    assert req.events.filter(kind="unassigned", message__contains="Sick").exists()

    response = coordinator_client.post(reverse("scheduling:assign", args=[req.pk]), {}, follow=True)
    assert "Choose an interpreter" in response.content.decode()


def test_next_parameter_returns_to_the_board(coordinator_client, staffed):
    req, ana, _ = staffed
    response = coordinator_client.post(
        reverse("scheduling:assign", args=[req.pk]),
        {"interpreter": ana.pk, "next": reverse("scheduling:board")},
    )
    assert response["Location"] == reverse("scheduling:board")


def test_switch_to_video_and_cancel(requester_client, staffed):
    req, *_ = staffed
    response = requester_client.post(reverse("scheduling:video", args=[req.pk]), follow=True)
    assert "Switched to video" in response.content.decode()
    response = requester_client.post(reverse("scheduling:video", args=[req.pk]), follow=True)
    assert "Only unassigned in-person requests" in response.content.decode()
    requester_client.post(reverse("scheduling:cancel", args=[req.pk]), {"reason": "Moved"})
    req.refresh_from_db()
    assert req.status == Status.CANCELLED
    assert req.cancel_reason == "Moved"
    page = requester_client.get(req.get_absolute_url()).content.decode()
    assert "Reason: Moved" in page


def test_record_outcome(requester_client, make_request, make_interpreter):
    person = make_interpreter("Ana")
    req = make_request(starts_at=at_local(-1, 9), status=Status.ASSIGNED, interpreter=person)
    page = requester_client.get(req.get_absolute_url())
    form = page.context["outcome_form"]
    assert form.fields["actual_minutes"].initial == 60
    assert [c for c, _ in form.fields["outcome"].choices][0] == "completed"

    bad = requester_client.post(
        reverse("scheduling:outcome", args=[req.pk]), {"outcome": "nonsense"}, follow=True
    )
    assert "Select a valid choice" in bad.content.decode()
    requester_client.post(
        reverse("scheduling:outcome", args=[req.pk]),
        {"outcome": "completed", "actual_minutes": 45, "notes": "Went well"},
    )
    req.refresh_from_db()
    assert (req.status, req.outcome, req.actual_minutes) == (Status.CLOSED, "completed", 45)
    assert "Went well" in requester_client.get(req.get_absolute_url()).content.decode()


def test_unfilled_outcome_choices(requester_client, make_request):
    req = make_request(starts_at=at_local(-1, 9))
    form = requester_client.get(req.get_absolute_url()).context["outcome_form"]
    assert [c for c, _ in form.fields["outcome"].choices][0] == "unfilled"


# --- Interpreters -----------------------------------------------------------


def test_interpreter_pages(coordinator_client, staffed, make_request):
    req, ana, luis = staffed
    dispatch.send_offer_wave(req)
    make_request(
        starts_at=at_local(-2, 9), status=Status.CLOSED, interpreter=ana, outcome="completed"
    )
    listing = coordinator_client.get(reverse("scheduling:interpreters"))
    assert [p.name for p in listing.context["interpreters"]] == ["Ana Ramirez", "Luis Moreno"]
    filtered = coordinator_client.get(reverse("scheduling:interpreters"), {"language": "vi"})
    assert list(filtered.context["interpreters"]) == []

    page = coordinator_client.get(reverse("scheduling:interpreter", args=[ana.pk]))
    assert page.context["jobs_this_year"] in {0, 1}
    assert page.context["feed_url"].startswith("https://langdesk.test/calendar/")
    old = ana.feed_token
    coordinator_client.post(reverse("scheduling:interpreter", args=[ana.pk]), {"action": "rotate"})
    ana.refresh_from_db()
    assert ana.feed_token != old


# --- Offer links ------------------------------------------------------------


def test_offer_link_get_never_changes_state(client, staffed):
    req, ana, _ = staffed
    offer = dispatch.offer_to(req, ana, None)
    url = offer.get_absolute_url()
    response = client.get(url)
    assert response.status_code == 200
    assert "can you take this?" in response.content.decode()
    offer.refresh_from_db()
    assert offer.status == Offer.Status.PENDING


def test_offer_link_accept_and_decline(client, staffed):
    req, ana, luis = staffed
    first = dispatch.offer_to(req, ana, None)
    second = dispatch.offer_to(req, luis, None)

    response = client.post(first.get_absolute_url(), {"action": "accept"})
    assert "You're confirmed" in response.content.decode()
    response = client.post(second.get_absolute_url(), {"action": "accept"})
    assert "This one is covered" in response.content.decode()
    assert client.get(first.get_absolute_url()).content.decode().count("You're confirmed") == 1


def test_offer_link_decline(client, staffed):
    req, ana, _ = staffed
    offer = dispatch.offer_to(req, ana, None)
    response = client.post(offer.get_absolute_url(), {"action": "decline"})
    assert "Thanks for letting us know" in response.content.decode()
    assert client.get("/o/not-a-token/").status_code == 404


def test_cancelled_offer_link(client, staffed):
    req, ana, _ = staffed
    offer = dispatch.offer_to(req, ana, None)
    dispatch.cancel(req, None)
    assert "No longer needed" in client.get(offer.get_absolute_url()).content.decode()
