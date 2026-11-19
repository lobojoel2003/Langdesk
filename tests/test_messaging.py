import datetime as dt
import json
from unittest import mock

import pytest
import requests
from django.core import mail
from django.urls import reverse

from langdesk.messaging import services, twilio_signature
from langdesk.messaging.backends import SMSError, get_sms_backend
from langdesk.messaging.backends.console import ConsoleSMSBackend
from langdesk.messaging.backends.twilio import TwilioSMSBackend
from langdesk.messaging.backends.webhook import WebhookSMSBackend
from langdesk.messaging.inbound import handle_sms, parse
from langdesk.messaging.models import InboundMessage, Notification
from langdesk.messaging.tasks import deliver_notification
from langdesk.scheduling.models import Offer
from langdesk.scheduling.services import dispatch

pytestmark = pytest.mark.django_db
Result = InboundMessage.Result


@pytest.fixture
def offered(make_interpreter, make_request, requester):
    ana = make_interpreter("Ana Ramirez", languages=[("es", "certified")])
    luis = make_interpreter("Luis Moreno")
    req = make_request()
    dispatch.send_offer_wave(req)
    return req, ana, luis


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("YES 4821", ("accept", "4821")),
        ("  yes!! ", ("accept", "")),
        ("Sí 1234", ("accept", "1234")),
        ("4821 ok", ("accept", "4821")),
        ("no 4821 sorry", ("decline", "4821")),
        ("STOP", ("stop", "")),
        ("start", ("start", "")),
        ("help", ("help", "")),
        ("what?", ("unknown", "")),
        ("", ("unknown", "")),
    ],
)
def test_parse(body, expected):
    assert parse(body) == expected


def test_yes_with_code_accepts(offered, sms):
    req, ana, _ = offered
    code = req.offers.get(interpreter=ana).code
    inbound = handle_sms("(555) 555-" + ana.phone[-4:], f"yes {code}")
    req.refresh_from_db()
    assert inbound.result == Result.ACCEPTED
    assert req.interpreter == ana
    assert "confirmed" in sms[-1].body


def test_yes_without_code_when_only_one_offer(offered):
    req, _, luis = offered
    assert handle_sms(luis.phone, "Yes").result == Result.ACCEPTED
    req.refresh_from_db()
    assert req.interpreter == luis


def test_ambiguous_yes_lists_codes(offered, make_request, sms):
    req, ana, _ = offered
    other = make_request(starts_in=dt.timedelta(days=4))
    dispatch.offer_to(other, ana, None)
    inbound = handle_sms(ana.phone, "YES")
    assert inbound.result == Result.AMBIGUOUS
    for offer in Offer.objects.filter(interpreter=ana):
        assert offer.code in inbound.reply
    assert sms[-1].body == inbound.reply


def test_no_declines_and_thanks(offered):
    req, ana, _ = offered
    inbound = handle_sms(ana.phone, "NO")
    assert inbound.result == Result.DECLINED
    assert req.offers.get(interpreter=ana).status == Offer.Status.DECLINED
    assert "thanks" in inbound.reply


def test_late_yes_is_told_it_is_filled(offered):
    req, ana, luis = offered
    code = req.offers.get(interpreter=luis).code
    handle_sms(ana.phone, "yes")
    inbound = handle_sms(luis.phone, f"yes {code}")
    assert inbound.result == Result.ALREADY_FILLED
    assert "already filled" in inbound.reply


def test_unknown_code_and_no_offers(offered, make_interpreter):
    _, ana, _ = offered
    assert handle_sms(ana.phone, "yes 0000").result == Result.NO_OFFER
    idle = make_interpreter("Idle")
    assert handle_sms(idle.phone, "yes").result == Result.NO_OFFER


def test_stop_start_help_and_strangers(offered, sms):
    _, ana, _ = offered
    sms.clear()
    assert handle_sms(ana.phone, "STOP").result == Result.STOP
    ana.refresh_from_db()
    assert ana.sms_opt_out
    assert sms == []  # carriers confirm opt-outs themselves
    assert handle_sms(ana.phone, "START").result == Result.START
    ana.refresh_from_db()
    assert not ana.sms_opt_out
    assert "Language access desk" in handle_sms(ana.phone, "HELP").reply
    assert handle_sms(ana.phone, "hello?").result == Result.UNRECOGNISED
    stranger = handle_sms("+19998887777", "YES")
    assert stranger.result == Result.UNKNOWN_SENDER
    assert stranger.reply == ""


def test_opted_out_interpreters_get_email_only(make_interpreter, make_request, sms):
    person = make_interpreter("Opted Out", sms_opt_out=True)
    dispatch.send_offer_wave(make_request())
    assert sms == []
    assert [m.to for m in mail.outbox] == [[person.email]]


# --- Webhooks ---------------------------------------------------------------


def _twilio_post(client, params, *, token="twilio-test-token"):
    url = "https://langdesk.test" + reverse("messaging:twilio")
    signature = twilio_signature.compute(token, url, {k: [v] for k, v in params.items()})
    return client.post(reverse("messaging:twilio"), params, HTTP_X_TWILIO_SIGNATURE=signature)


def test_twilio_webhook_accepts_signed_requests(client, offered):
    req, ana, _ = offered
    response = _twilio_post(client, {"From": ana.phone, "Body": "YES", "To": "+15550000000"})
    assert response.status_code == 200
    assert response["Content-Type"] == "text/xml"
    assert b"<Response>" in response.content
    req.refresh_from_db()
    assert req.interpreter == ana


def test_twilio_webhook_rejects_bad_signatures(client, offered):
    _, ana, _ = offered
    response = _twilio_post(client, {"From": ana.phone, "Body": "YES"}, token="wrong")
    assert response.status_code == 403
    assert not InboundMessage.objects.exists()
    assert client.get(reverse("messaging:twilio")).status_code == 405


def test_twilio_signature_requires_a_token():
    assert not twilio_signature.is_valid("", "https://x", {}, "sig")


def test_generic_webhook(client, offered):
    req, ana, _ = offered
    url = reverse("messaging:inbound")
    auth = {"HTTP_AUTHORIZATION": "Bearer inbound-test-token"}
    assert client.post(url, {"from": ana.phone, "body": "yes"}).status_code == 403
    assert client.post(url, "{", content_type="application/json", **auth).status_code == 400
    assert client.post(url, {"body": "yes"}, **auth).status_code == 400

    response = client.post(
        url, json.dumps({"from": ana.phone, "body": "YES"}), content_type="application/json", **auth
    )
    assert response.status_code == 200
    assert response.json() == {"result": "accepted", "reply": ""}
    form = client.post(url, {"from": ana.phone, "body": "help"}, **auth)
    assert form.json()["result"] == "help"


def test_simulator(coordinator_client, offered, settings):
    req, ana, _ = offered
    url = reverse("messaging:simulator")
    page = coordinator_client.get(url, {"interpreter": ana.pk})
    assert page.status_code == 200
    assert "Spanish interpreter needed" in page.content.decode()
    response = coordinator_client.post(url, {"interpreter": ana.pk, "body": "yes"})
    assert response.status_code == 302
    req.refresh_from_db()
    assert req.interpreter == ana
    assert coordinator_client.post(url, {"interpreter": ana.pk, "body": " "}).status_code == 302
    assert coordinator_client.get(url).status_code == 200
    settings.LANGDESK_SMS_SIMULATOR = False
    assert coordinator_client.get(url).status_code == 404


def test_simulator_is_for_coordinators(requester_client):
    response = requester_client.get(reverse("messaging:simulator"))
    assert response.status_code == 302


# --- Delivery ---------------------------------------------------------------


def test_dedupe_keys_make_sends_idempotent():
    first = services.queue_sms("+15550001111", "hi", kind="reply", dedupe_key="k1")
    again = services.queue_sms("+15550001111", "hi", kind="reply", dedupe_key="k1")
    assert first is not None and again is None
    assert str(first) == "Reply to inbound text via sms to +15550001111"


def test_failed_delivery_is_recorded_and_retried(settings):
    settings.LANGDESK_SMS_BACKEND = "langdesk.messaging.backends.twilio.TwilioSMSBackend"
    settings.TWILIO_ACCOUNT_SID = ""
    note = services.queue_sms("+15550001111", "hello", kind="reply")
    note.refresh_from_db()
    assert note.status == Notification.Status.FAILED
    assert "not configured" in note.error
    assert note.attempts == 1

    settings.LANGDESK_SMS_BACKEND = "langdesk.messaging.backends.locmem.LocMemSMSBackend"
    assert services.deliver(note.pk) is True
    note.refresh_from_db()
    assert (note.status, note.attempts, note.error) == ("sent", 2, "")
    assert services.deliver(note.pk) is True  # already sent
    assert services.deliver(999999) is False


def test_celery_task_retries_failures(settings):
    settings.LANGDESK_SMS_BACKEND = "langdesk.messaging.backends.twilio.TwilioSMSBackend"
    settings.TWILIO_ACCOUNT_SID = ""
    settings.LANGDESK_TASKS_EAGER = True
    note = services.queue_sms("+15550001111", "hello", kind="reply")
    with mock.patch.object(
        deliver_notification, "retry", side_effect=RuntimeError("retry")
    ) as retry:
        with pytest.raises(RuntimeError):
            deliver_notification.run(note.pk)
    assert retry.call_args.kwargs["countdown"] == 120


def test_queued_delivery_waits_for_commit(settings, django_capture_on_commit_callbacks):
    settings.LANGDESK_TASKS_EAGER = False
    with mock.patch("langdesk.messaging.tasks.deliver_notification.delay") as delay:
        with django_capture_on_commit_callbacks(execute=True):
            note = services.queue_sms("+15550001111", "hello", kind="reply")
        delay.assert_called_once_with(note.pk)


def test_email_failures_are_recorded(settings):
    settings.EMAIL_BACKEND = "tests.test_messaging.BrokenEmailBackend"
    note = services.queue_email("a@example.org", "Hi", "Body", kind="reply")
    note.refresh_from_db()
    assert note.status == "failed"


class BrokenEmailBackend:
    def __init__(self, *args, **kwargs):
        pass

    def send_messages(self, messages):
        raise OSError("SMTP down")


# --- Backends ---------------------------------------------------------------


def test_console_backend_logs(caplog):
    with caplog.at_level("INFO", logger="langdesk.sms"):
        message_id = ConsoleSMSBackend().send("+15550001111", "hello")
    assert message_id.startswith("console-")
    assert "hello" in caplog.text


def test_get_sms_backend_uses_settings(settings):
    settings.LANGDESK_SMS_BACKEND = "langdesk.messaging.backends.console.ConsoleSMSBackend"
    assert isinstance(get_sms_backend(), ConsoleSMSBackend)


def _response(status=201, payload=None, text=""):
    response = mock.Mock(status_code=status, text=text)
    if payload is None:
        response.json.side_effect = ValueError
    else:
        response.json.return_value = payload
    return response


def test_twilio_backend(settings):
    settings.TWILIO_ACCOUNT_SID = "AC123"
    settings.TWILIO_AUTH_TOKEN = "secret"
    settings.TWILIO_FROM_NUMBER = "+15550009999"
    settings.TWILIO_MESSAGING_SERVICE_SID = ""
    with mock.patch("requests.post", return_value=_response(payload={"sid": "SM1"})) as post:
        assert TwilioSMSBackend().send("+15550001111", "hi") == "SM1"
    assert post.call_args.kwargs["data"] == {
        "To": "+15550001111",
        "Body": "hi",
        "From": "+15550009999",
    }
    assert post.call_args.kwargs["auth"] == ("AC123", "secret")

    settings.TWILIO_MESSAGING_SERVICE_SID = "MG1"
    with mock.patch("requests.post", return_value=_response(payload={"sid": "SM2"})) as post:
        TwilioSMSBackend().send("+15550001111", "hi")
    assert post.call_args.kwargs["data"]["MessagingServiceSid"] == "MG1"

    with mock.patch("requests.post", return_value=_response(400, {"message": "Bad number"})):
        with pytest.raises(SMSError, match="Bad number"):
            TwilioSMSBackend().send("+1", "hi")
    with mock.patch("requests.post", return_value=_response(500, None, "oops")):
        with pytest.raises(SMSError, match="oops"):
            TwilioSMSBackend().send("+1", "hi")
    with mock.patch("requests.post", side_effect=requests.ConnectionError("down")):
        with pytest.raises(SMSError, match="down"):
            TwilioSMSBackend().send("+1", "hi")

    settings.TWILIO_MESSAGING_SERVICE_SID = ""
    settings.TWILIO_FROM_NUMBER = ""
    with pytest.raises(SMSError, match="TWILIO_FROM_NUMBER"):
        TwilioSMSBackend().send("+1", "hi")


def test_webhook_backend(settings):
    settings.LANGDESK_SMS_WEBHOOK_URL = ""
    with pytest.raises(SMSError, match="LANGDESK_SMS_WEBHOOK_URL"):
        WebhookSMSBackend().send("+1", "hi")

    settings.LANGDESK_SMS_WEBHOOK_URL = "https://relay.example.org/sms"
    settings.LANGDESK_SMS_WEBHOOK_TOKEN = "tok"
    with mock.patch("requests.post", return_value=_response(200, {"id": 42})) as post:
        assert WebhookSMSBackend().send("+15550001111", "hi") == "42"
    assert post.call_args.kwargs["json"] == {"to": "+15550001111", "body": "hi"}
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer tok"

    with mock.patch("requests.post", return_value=_response(200, None)):
        assert WebhookSMSBackend().send("+1", "hi") == ""
    with mock.patch("requests.post", return_value=_response(502, None, "bad gateway")):
        with pytest.raises(SMSError, match="502"):
            WebhookSMSBackend().send("+1", "hi")
    with mock.patch("requests.post", side_effect=requests.Timeout("slow")):
        with pytest.raises(SMSError, match="slow"):
            WebhookSMSBackend().send("+1", "hi")


def test_admin_retry_action(admin_client, settings):
    settings.LANGDESK_SMS_BACKEND = "langdesk.messaging.backends.twilio.TwilioSMSBackend"
    settings.TWILIO_ACCOUNT_SID = ""
    note = services.queue_sms("+15550001111", "hello", kind="reply")
    settings.LANGDESK_SMS_BACKEND = "langdesk.messaging.backends.locmem.LocMemSMSBackend"
    response = admin_client.post(
        reverse("admin:messaging_notification_changelist"),
        {"action": "retry", "_selected_action": [note.pk]},
        follow=True,
    )
    assert "Re-sent 1 message" in response.content.decode()
    assert admin_client.get(reverse("admin:messaging_inboundmessage_changelist")).status_code == 200
