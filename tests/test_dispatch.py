import datetime as dt

import pytest
from django.core import mail
from django.utils import timezone

from langdesk.messaging.models import Notification
from langdesk.scheduling.models import InterpreterRequest, Modality, Offer, RequestEvent
from langdesk.scheduling.services import dispatch
from langdesk.scheduling.services.dispatch import DispatchError, Reply

from .conftest import at_local

pytestmark = pytest.mark.django_db
Status = InterpreterRequest.Status
Outcome = InterpreterRequest.Outcome


@pytest.fixture
def team(make_interpreter, clinic):
    return [
        make_interpreter("Ana Ramirez", languages=[("es", "certified")], home_location=clinic),
        make_interpreter("Carmen Diaz", languages=[("es", "certified")]),
        make_interpreter("Luis Moreno", employment="contractor"),
        make_interpreter("Rosa Tzoc", employment="contractor"),
    ]


def new_request(make_request, requester, **fields):
    """Build an unsaved request and create it through the dispatcher."""
    req = make_request(**fields)
    data = {f.name: getattr(req, f.name) for f in InterpreterRequest._meta.concrete_fields}
    req.delete()
    data.pop("id")
    data.pop("reference")
    return dispatch.create_request(InterpreterRequest(**data), requester)


def kinds(req):
    return list(req.events.values_list("kind", flat=True))


def test_new_request_offers_the_top_three(team, make_request, requester, sms):
    req = new_request(make_request, requester)

    offers = list(req.offers.order_by("-score"))
    assert [o.interpreter.name for o in offers] == ["Ana Ramirez", "Carmen Diaz", "Luis Moreno"]
    assert req.reference == f"LD-{req.pk:05d}"
    assert kinds(req) == ["created", "offered"]
    assert {m.to for m in sms} == {o.interpreter.phone for o in offers}
    first = next(m for m in sms if m.to == offers[0].interpreter.phone)
    assert f"YES {offers[0].code}" in first.body
    assert "Spanish interpreter needed" in first.body
    assert offers[0].get_absolute_url() in first.body
    assert len(mail.outbox) == 3  # interpreters prefer both channels by default


def test_auto_dispatch_can_be_turned_off(team, make_request, requester, settings):
    settings.LANGDESK_AUTO_DISPATCH = False
    req = new_request(make_request, requester)
    assert not req.offers.exists()


def test_video_requests_get_a_jitsi_link(team, make_request, requester, settings):
    settings.LANGDESK_JITSI_BASE_URL = "https://meet.example.org"
    req = new_request(make_request, requester, modality=Modality.VIDEO)
    assert req.video_url.startswith("https://meet.example.org/langdesk-")
    assert len(req.video_url.rsplit("-", 1)[1]) == 20


def test_first_to_accept_wins(team, make_request, requester, sms):
    req = new_request(make_request, requester)
    first, second, third = req.offers.order_by("-score")
    sms.clear()
    mail.outbox.clear()

    assert dispatch.accept_offer(second, channel="sms") == Reply.ACCEPTED
    assert dispatch.accept_offer(first, channel="web") == Reply.FILLED

    req.refresh_from_db()
    assert req.status == Status.ASSIGNED
    assert req.interpreter == second.interpreter
    assert req.assigned_at is not None
    statuses = dict(req.offers.values_list("interpreter__name", "status"))
    assert statuses == {
        "Ana Ramirez": Offer.Status.WITHDRAWN,
        "Carmen Diaz": Offer.Status.ACCEPTED,
        "Luis Moreno": Offer.Status.WITHDRAWN,
    }
    bodies = {m.to: m.body for m in sms}
    assert "confirmed" in bodies[second.interpreter.phone]
    assert "has been filled" in bodies[third.interpreter.phone]
    subjects = [m.subject for m in mail.outbox]
    assert "Interpreter confirmed for " + req.reference in subjects
    invite = next(m for m in mail.outbox if m.subject.startswith("Confirmed"))
    assert "METHOD:REQUEST" in invite.attachments[0].get_payload(decode=True).decode()
    # Accepting again is harmless.
    assert dispatch.accept_offer(second, channel="sms") == Reply.ACCEPTED


def test_late_acceptance_of_an_expired_offer_still_counts(team, make_request, requester):
    req = new_request(make_request, requester)
    offer = req.offers.order_by("-score").first()
    dispatch.expire_offers(now=timezone.now() + dt.timedelta(hours=1))
    offer.refresh_from_db()
    assert offer.status == Offer.Status.EXPIRED
    assert dispatch.accept_offer(offer, channel="sms") == Reply.ACCEPTED


def test_decline_sends_the_next_wave_when_nobody_is_left(team, make_request, requester):
    req = new_request(make_request, requester)
    for offer in req.offers.all():
        assert dispatch.decline_offer(offer, channel="sms") == Reply.DECLINED
    pending = req.offers.filter(status=Offer.Status.PENDING)
    assert [o.interpreter.name for o in pending] == ["Rosa Tzoc"]
    assert pending.get().wave == 2
    assert dispatch.decline_offer(
        req.offers.get(interpreter__name="Ana Ramirez"), channel="sms"
    ) == (Reply.NOT_PENDING)


def test_exhausted_roster_alerts_coordinators_once(team, make_request, requester, coordinator):
    req = new_request(make_request, requester)
    for offer in list(req.offers.all()):
        dispatch.decline_offer(offer, channel="sms")
    dispatch.decline_offer(req.offers.get(status=Offer.Status.PENDING), channel="web")

    alerts = Notification.objects.filter(kind=Notification.Kind.COORDINATOR_ALERT)
    assert alerts.count() == 1
    assert alerts.get().to_address == coordinator.email
    assert "no available interpreter" in alerts.get().body
    assert dispatch.send_offer_wave(req) == []
    assert alerts.count() == 1
    assert "alert" in kinds(req)


def test_offer_to_a_specific_person(team, make_request, requester, coordinator, make_interpreter):
    req = new_request(make_request, requester)
    offer = dispatch.offer_to(req, team[3], coordinator)
    assert offer.sent_by == coordinator
    with pytest.raises(DispatchError, match="already has this offer"):
        dispatch.offer_to(req, team[3], coordinator)
    remote_only = make_interpreter("Remote Only", offers_in_person=False)
    with pytest.raises(DispatchError, match="Does not work in person"):
        dispatch.offer_to(req, remote_only, coordinator)


def test_direct_assignment_and_reassignment(team, make_request, requester, coordinator, sms):
    req = new_request(make_request, requester)
    ana, carmen = team[0], team[1]

    dispatch.assign(req, carmen, coordinator)
    req.refresh_from_db()
    assert req.interpreter == carmen
    assert req.offers.get(interpreter=carmen).response_channel == "coordinator"
    assert dispatch.assign(req, carmen, coordinator).interpreter == carmen  # no-op

    sms.clear()
    dispatch.assign(req, ana, coordinator)
    req.refresh_from_db()
    assert req.interpreter == ana
    assert any("CANCELLED" in m.body for m in sms if m.to == carmen.phone)
    assert "unassigned" in kinds(req)


def test_assign_rejects_people_without_the_language(make_interpreter, make_request, coordinator):
    req = make_request()
    other = make_interpreter("Vietnamese", languages=[("vi", "qualified")])
    with pytest.raises(DispatchError, match="doesn't interpret Spanish"):
        dispatch.assign(req, other, coordinator)
    req.status = Status.CLOSED
    req.save()
    with pytest.raises(DispatchError, match="closed"):
        dispatch.assign(req, other, coordinator)


def test_unassign_reopens_and_reoffers_without_the_same_person(
    team, make_request, requester, coordinator
):
    req = new_request(make_request, requester)
    offer = req.offers.order_by("-score").first()
    dispatch.accept_offer(offer, channel="sms")

    dispatch.unassign(req, coordinator, "Sick")

    req.refresh_from_db()
    assert req.status == Status.OPEN
    assert req.interpreter is None
    offer.refresh_from_db()
    assert offer.status == Offer.Status.DECLINED
    pending = set(req.offers.filter(status="pending").values_list("interpreter__name", flat=True))
    assert pending and offer.interpreter.name not in pending
    with pytest.raises(DispatchError):
        dispatch.unassign(make_request(), coordinator)


def test_cancel_notifies_everyone_and_records_the_outcome(
    team, make_request, requester, coordinator, sms
):
    req = new_request(make_request, requester)
    dispatch.assign(req, team[0], coordinator)
    sms.clear()

    dispatch.cancel(req, coordinator, "Patient rescheduled")

    req.refresh_from_db()
    assert req.status == Status.CANCELLED
    assert req.outcome == Outcome.CANCELLED
    assert req.outcome_recorded_by == coordinator
    assert [m.to for m in sms] == [team[0].phone]
    assert "Patient rescheduled" in sms[0].body
    cancel_mail = next(m for m in mail.outbox if m.subject.startswith("Cancelled"))
    assert "METHOD:CANCEL" in cancel_mail.attachments[0].get_payload(decode=True).decode()
    assert any(m.subject == f"{req.reference} was cancelled" for m in mail.outbox)
    with pytest.raises(DispatchError):
        dispatch.cancel(req, coordinator)


def test_requester_cancelling_their_own_request_gets_no_email(team, make_request, requester):
    req = new_request(make_request, requester)
    mail.outbox.clear()
    dispatch.cancel(req, requester)
    assert all(requester.email not in m.to for m in mail.outbox)
    assert set(req.offers.values_list("status", flat=True)) == {Offer.Status.WITHDRAWN}


def test_fall_back_to_video(team, make_request, requester, make_interpreter):
    remote = make_interpreter("Remote Only", offers_in_person=False)
    req = new_request(make_request, requester)
    assert dispatch.fall_back_to_video(req) is True

    req.refresh_from_db()
    assert req.modality == Modality.VIDEO
    assert req.requested_modality == Modality.IN_PERSON
    assert req.fell_back_to_video
    assert req.video_url
    assert req.offers.filter(interpreter=remote).exists()
    assert any(m.subject.endswith("will use video interpreting") for m in mail.outbox)
    assert dispatch.fall_back_to_video(req) is False


def test_record_outcome_rules(team, make_request, requester, coordinator):
    req = make_request()
    with pytest.raises(DispatchError, match="Assign the interpreter"):
        dispatch.record_outcome(req, outcome=Outcome.COMPLETED, actor=coordinator)
    dispatch.record_outcome(req, outcome=Outcome.UNFILLED, actor=coordinator, notes="No one")
    req.refresh_from_db()
    assert (req.status, req.outcome, req.outcome_notes) == (
        Status.CLOSED,
        Outcome.UNFILLED,
        "No one",
    )

    cancelled = make_request(status=Status.CANCELLED)
    with pytest.raises(DispatchError):
        dispatch.record_outcome(cancelled, outcome=Outcome.UNFILLED, actor=coordinator)

    done = make_request(status=Status.ASSIGNED, interpreter=team[0])
    dispatch.record_outcome(done, outcome=Outcome.COMPLETED, actor=coordinator, actual_minutes=50)
    done.refresh_from_db()
    assert done.billable_minutes == 50
    assert done.served


def test_editing_an_assigned_request_sends_an_update(
    team, make_request, requester, coordinator, sms
):
    req = new_request(make_request, requester)
    dispatch.assign(req, team[0], coordinator)
    req.refresh_from_db()
    sequence = req.sequence
    sms.clear()

    req.starts_at += dt.timedelta(hours=1)
    req.ends_at += dt.timedelta(hours=1)
    req.save()
    dispatch.update_request(req, ["starts_at", "ends_at"], coordinator)

    req.refresh_from_db()
    assert req.sequence == sequence + 1
    assert [m.to for m in sms] == [team[0].phone]
    assert sms[0].body.startswith("Test Clinic: UPDATED")
    assert dispatch.update_request(req, [], coordinator) is req


def test_editing_an_open_request_reoffers(team, make_request, requester, coordinator):
    req = new_request(make_request, requester)
    first_wave = set(req.offers.values_list("pk", flat=True))
    req.modality = Modality.VIDEO
    req.save()
    dispatch.update_request(req, ["modality"], coordinator)
    req.refresh_from_db()
    assert req.video_url
    assert req.requested_modality == Modality.VIDEO
    assert set(req.offers.filter(pk__in=first_wave).values_list("status", flat=True)) == {
        Offer.Status.WITHDRAWN
    }
    assert req.offers.filter(status="pending").exclude(pk__in=first_wave).count() == 3

    req.notes = "Use side door"
    req.save()
    dispatch.update_request(req, ["notes"], coordinator)
    assert req.offers.filter(status="pending").count() == 3


def test_reminders_are_sent_once_at_the_closest_lead(team, make_request, coordinator, sms):
    req = make_request(starts_at=at_local(5, 10))
    dispatch.assign(req, team[0], coordinator)
    InterpreterRequest.objects.filter(pk=req.pk).update(
        assigned_at=req.starts_at - dt.timedelta(days=3)
    )
    sms.clear()

    assert dispatch.send_due_reminders(now=req.starts_at - dt.timedelta(hours=30)) == 0
    assert dispatch.send_due_reminders(now=req.starts_at - dt.timedelta(hours=23)) == 1
    assert dispatch.send_due_reminders(now=req.starts_at - dt.timedelta(hours=22)) == 0
    assert dispatch.send_due_reminders(now=req.starts_at - dt.timedelta(minutes=90)) == 1
    assert dispatch.send_due_reminders(now=req.starts_at - dt.timedelta(minutes=80)) == 0
    assert [m.body.split(":")[0] for m in sms] == ["Test Clinic reminder"] * 2
    assert "tomorrow" in sms[0].body and "in 2 hours" in sms[1].body
    assert kinds(req).count("reminder") == 2


def test_no_reminder_when_assigned_inside_the_window(team, make_request, coordinator):
    req = make_request(starts_at=at_local(5, 10))
    dispatch.assign(req, team[0], coordinator)
    InterpreterRequest.objects.filter(pk=req.pk).update(
        assigned_at=req.starts_at - dt.timedelta(hours=3)
    )
    assert dispatch.send_due_reminders(now=req.starts_at - dt.timedelta(hours=20)) == 0
    assert dispatch.send_due_reminders(now=req.starts_at - dt.timedelta(minutes=100)) == 1


def test_reminders_can_be_disabled(settings):
    settings.LANGDESK_REMINDER_MINUTES = []
    assert dispatch.send_due_reminders() == 0


def test_dispatcher_expires_offers_and_sends_the_next_wave(team, make_request, requester):
    req = new_request(make_request, requester, starts_in=dt.timedelta(days=3))
    later = timezone.now() + dt.timedelta(minutes=30)

    stats = dispatch.run_dispatcher(now=later)

    assert stats["expired"] == 3
    assert stats["waves"] == 1
    assert "expired" in kinds(req)
    assert req.offers.filter(status="pending").get().interpreter.name == "Rosa Tzoc"


def test_dispatcher_falls_back_to_video_close_to_start(team, make_request, requester, settings):
    settings.LANGDESK_AUTO_DISPATCH = False
    req = new_request(make_request, requester, starts_in=dt.timedelta(minutes=45))
    far = new_request(make_request, requester, starts_in=dt.timedelta(hours=5))
    stats = dispatch.run_dispatcher()
    assert stats["fallbacks"] == 1
    req.refresh_from_db()
    far.refresh_from_db()
    assert req.fell_back_to_video
    assert not far.fell_back_to_video
    settings.LANGDESK_VIDEO_FALLBACK_MINUTES = 0
    assert dispatch.run_dispatcher()["fallbacks"] == 0


def test_events_have_readable_actor_labels(team, make_request, requester, coordinator):
    req = new_request(make_request, requester)
    dispatch.accept_offer(req.offers.first(), channel="sms")
    labels = {e.kind: e.actor_label for e in req.events.all()}
    assert labels["created"] == "Grace Kim"
    assert labels["offered"] == "Langdesk"
    assert labels["accepted"] in {p.name for p in team}
    assert str(req.events.first()).startswith(req.reference)
    assert RequestEvent.objects.filter(request=req, kind="assigned").exists()
