import datetime as dt

import pytest
from django.utils import timezone

from langdesk.roster.models import AvailabilityWindow, Interpreter, TimeOff
from langdesk.scheduling.models import InterpreterRequest, Modality, Offer
from langdesk.scheduling.services.matching import match

from .conftest import at_local

CERT = "certified"
QUAL = "qualified"
pytestmark = pytest.mark.django_db


def names(found):
    return [c.interpreter.name for c in found.candidates]


def excluded(found):
    return {e.interpreter.name: e.reason for e in found.excluded}


def test_ranks_certified_staff_at_same_site_first(make_interpreter, make_request, clinic):
    make_interpreter("Contract Qualified", employment="contractor")
    make_interpreter("Staff Certified Here", languages=[("es", CERT)], home_location=clinic)
    make_interpreter("Staff Certified", languages=[("es", CERT)])
    make_interpreter(
        "Agency Certified", languages=[("es", CERT)], employment="agency", agency_name="Lakeside"
    )

    found = match(make_request())

    assert names(found) == [
        "Staff Certified Here",
        "Staff Certified",
        "Agency Certified",
        "Contract Qualified",
    ]
    top = found.candidates[0]
    assert {"Certified", "Staff", "Same site", "Free that day"} <= set(top.reasons)
    assert "Lakeside" in found.candidates[2].reasons
    assert 0 < top.percent <= 100


def test_only_speakers_of_the_language_are_considered(make_interpreter, make_request):
    make_interpreter("Vietnamese Only", languages=[("vi", CERT)])
    make_interpreter("Inactive", is_active=False)
    assert names(match(make_request())) == []


@pytest.mark.parametrize(
    ("modality", "field"),
    [(Modality.IN_PERSON, "offers_in_person"), (Modality.VIDEO, "offers_video")],
)
def test_excludes_interpreters_who_do_not_work_that_way(
    make_interpreter, make_request, modality, field
):
    make_interpreter("No", **{field: False})
    found = match(make_request(modality=modality))
    assert excluded(found)["No"].startswith("Does not work")


def test_excludes_sites_they_do_not_travel_to(make_interpreter, make_request, clinic, school):
    person = make_interpreter("School Only")
    person.serves_locations.add(school)
    based_here = make_interpreter("Based Here", home_location=clinic)
    based_here.serves_locations.add(school)

    found = match(make_request(location=clinic))

    assert excluded(found) == {"School Only": "Does not travel to Main Clinic"}
    assert names(found) == ["Based Here"]
    # Remote work is not limited by site.
    assert "School Only" in names(match(make_request(modality=Modality.VIDEO, location=clinic)))


def test_excludes_time_off_and_hours(make_interpreter, make_request):
    req = make_request(starts_at=at_local(3, 18))
    away = make_interpreter("Away")
    TimeOff.objects.create(
        interpreter=away,
        starts_at=req.starts_at - dt.timedelta(days=1),
        ends_at=req.starts_at + dt.timedelta(days=1),
    )
    daytime = make_interpreter("Daytime")
    AvailabilityWindow.objects.create(
        interpreter=daytime,
        weekday=timezone.localtime(req.starts_at).weekday(),
        start_time=dt.time(8),
        end_time=dt.time(17),
    )
    evenings = make_interpreter("Evenings")
    AvailabilityWindow.objects.create(
        interpreter=evenings,
        weekday=timezone.localtime(req.starts_at).weekday(),
        start_time=dt.time(17),
        end_time=dt.time(21),
    )

    found = match(req)

    assert excluded(found) == {"Away": "On time off", "Daytime": "Outside working hours"}
    assert names(found) == ["Evenings"]


def test_excludes_double_bookings_with_travel_buffer(make_interpreter, make_request):
    busy = make_interpreter("Busy")
    make_interpreter("Free")
    start = at_local(2, 10)
    make_request(
        starts_at=start - dt.timedelta(minutes=70),
        status=InterpreterRequest.Status.ASSIGNED,
        interpreter=busy,
    )  # ends 10 minutes before: inside the 15 minute buffer
    req = make_request(starts_at=start)

    found = match(req)

    assert excluded(found)["Busy"].startswith("Booked at")
    assert names(found) == ["Free"]


def test_back_to_back_remote_work_is_fine(make_interpreter, make_request):
    person = make_interpreter("Remote")
    start = at_local(2, 10)
    make_request(
        starts_at=start - dt.timedelta(minutes=60),
        modality=Modality.VIDEO,
        status=InterpreterRequest.Status.ASSIGNED,
        interpreter=person,
    )
    found = match(make_request(starts_at=start, modality=Modality.VIDEO))
    assert names(found) == ["Remote"]
    assert "1 job that day" in found.candidates[0].cautions


def test_cancelled_bookings_do_not_block(make_interpreter, make_request):
    person = make_interpreter("Person")
    start = at_local(2, 10)
    make_request(
        starts_at=start,
        status=InterpreterRequest.Status.CANCELLED,
        interpreter=person,
        outcome=InterpreterRequest.Outcome.CANCELLED,
    )
    assert names(match(make_request(starts_at=start))) == ["Person"]


def test_daily_limit(make_interpreter, make_request):
    person = make_interpreter("Limited", max_daily_assignments=1)
    make_request(
        starts_at=at_local(2, 8),
        status=InterpreterRequest.Status.ASSIGNED,
        interpreter=person,
    )
    assert excluded(match(make_request(starts_at=at_local(2, 14)))) == {
        "Limited": "Reached daily limit"
    }


def test_busier_interpreters_rank_lower(make_interpreter, make_request):
    busy = make_interpreter("Aaron Busy")
    make_interpreter("Zed Free")
    make_request(
        starts_at=at_local(2, 8), status=InterpreterRequest.Status.ASSIGNED, interpreter=busy
    )
    assert names(match(make_request(starts_at=at_local(2, 14)))) == ["Zed Free", "Aaron Busy"]


def test_declined_offers_exclude_but_withdrawn_offers_do_not(make_interpreter, make_request):
    no = make_interpreter("Said No")
    withdrawn = make_interpreter("Withdrawn")
    req = make_request()
    expires = timezone.now() + dt.timedelta(minutes=20)
    Offer.objects.create(
        request=req, interpreter=no, code="1111", status="declined", expires_at=expires
    )
    Offer.objects.create(
        request=req, interpreter=withdrawn, code="2222", status="withdrawn", expires_at=expires
    )

    found = match(req)

    assert excluded(found) == {"Said No": "Declined this request"}
    assert [c.interpreter.name for c in found.fresh()] == ["Withdrawn"]


def test_pending_offers_are_not_fresh(make_interpreter, make_request):
    person = make_interpreter("Asked")
    req = make_request()
    Offer.objects.create(request=req, interpreter=person, code="1234", expires_at=timezone.now())
    found = match(req)
    assert names(found) == ["Asked"]
    assert found.fresh() == []


def test_unreachable_interpreters_are_excluded(make_interpreter, make_request):
    make_interpreter("Ghost", phone="", email="")
    assert excluded(match(make_request())) == {"Ghost": "No way to reach them"}


def test_continuity_and_reliability_bonuses(make_interpreter, make_request):
    known = make_interpreter("Knows Case")
    reliable = make_interpreter("Reliable One")
    make_interpreter("Newcomer")
    make_request(
        starts_at=at_local(-10, 9),
        appointment_ref="CASE-1",
        status=InterpreterRequest.Status.CLOSED,
        interpreter=known,
    )
    for i in range(5):
        past = make_request(starts_at=at_local(-20 - i, 9))
        Offer.objects.create(
            request=past,
            interpreter=reliable,
            code=f"{1000 + i}",
            status="accepted",
            expires_at=timezone.now(),
        )

    found = match(make_request(appointment_ref="CASE-1"))

    by_name = {c.interpreter.name: c for c in found.candidates}
    assert "Knows this case" in by_name["Knows Case"].reasons
    assert "Reliable" in by_name["Reliable One"].reasons
    assert by_name["Newcomer"].score < by_name["Reliable One"].score < by_name["Knows Case"].score


def test_expired_certification_counts_as_qualified(make_interpreter, make_request):
    person = make_interpreter("Lapsed", languages=[("es", CERT)])
    skill = person.language_skills.get()
    skill.credential_expires = timezone.localdate() - dt.timedelta(days=1)
    skill.save()
    candidate = match(make_request()).candidates[0]
    assert candidate.credential == QUAL
    assert "Certification expired" in candidate.cautions


def test_assigned_interpreter_is_not_listed(make_interpreter, make_request):
    person = make_interpreter("Assigned")
    req = make_request(status=InterpreterRequest.Status.ASSIGNED, interpreter=person)
    found = match(req)
    assert found.candidates == []
    assert found.excluded == []


def test_interpreter_helpers(make_interpreter):
    person: Interpreter = make_interpreter("Ana María Ramírez", preferred_channel="sms")
    assert person.short_name == "Ana R."
    assert person.initials == "AM"
    assert person.wants("sms")
    assert not person.wants("email")
    person.sms_opt_out = True
    assert not person.wants("sms")
    assert person.wants("email")  # falls back when texts are off
    solo = make_interpreter("Cher")
    assert solo.short_name == "Cher"
    old = solo.feed_token
    solo.rotate_feed_token()
    assert solo.feed_token != old
