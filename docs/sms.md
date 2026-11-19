# Text messages

Interpreters get offers, confirmations, reminders and cancellations by text, and accept by
replying. Langdesk talks to SMS providers through small, pluggable backends.

## What interpreters see

> Riverside Community Health: Spanish interpreter needed Thu Nov 19, 12:00–1:00 PM, in person
> at Riverside Community Clinic, Room 3. Reply YES 2100 to accept or NO 2100 to decline.
> https://langdesk.example.org/o/bVw5374yHHWqeZq8tewA-A/

Replies Langdesk understands (case-insensitive, punctuation ignored):

| Reply | Meaning |
|---|---|
| `YES 2100`, `Y`, `OK`, `ACCEPT`, `SÍ`, `OUI` | Accept. The code can be left out when there's only one open offer. |
| `NO 2100`, `N`, `DECLINE`, `PASS` | Decline. |
| `HELP`, `INFO` | How to reply, plus `LANGDESK_SUPPORT_CONTACT`. |
| `STOP`, `UNSUBSCRIBE`, `CANCEL`, `END`, `QUIT` | Stop texts. Offers then go by email only. |
| `START`, `UNSTOP` | Resume texts. |

The first interpreter to accept gets the job. Anyone who accepts after that is told it's filled.
Texts from numbers that aren't on the roster are logged and ignored.

Message wording lives in `langdesk/scheduling/templates/scheduling/messages/`. Override any file
with a template of the same name to change or translate it.

## Twilio

1. Buy a number (or create a Messaging Service) in the Twilio console.
2. Set:

   ```dotenv
   LANGDESK_SMS_BACKEND=langdesk.messaging.backends.twilio.TwilioSMSBackend
   TWILIO_ACCOUNT_SID=AC...
   TWILIO_AUTH_TOKEN=...
   TWILIO_FROM_NUMBER=+15555550100
   # or TWILIO_MESSAGING_SERVICE_SID=MG...
   ```

3. In the number's messaging settings, set **A message comes in** to *Webhook*,
   `https://langdesk.example.org/sms/twilio/`, *HTTP POST*.

Langdesk verifies the `X-Twilio-Signature` header with your auth token, so `LANGDESK_BASE_URL`
must match the public URL Twilio calls exactly (scheme and host).

US numbers need A2P 10DLC registration for application-to-person texts. Register your
organisation and a campaign for "appointment reminders and staff scheduling" in Twilio.

## Any other provider: the webhook backend

The webhook backend lets you connect any provider through a small relay (a serverless function,
n8n, an on-premise gateway).

**Outbound.** Langdesk POSTs JSON to your relay:

```dotenv
LANGDESK_SMS_BACKEND=langdesk.messaging.backends.webhook.WebhookSMSBackend
LANGDESK_SMS_WEBHOOK_URL=https://relay.example.org/send
LANGDESK_SMS_WEBHOOK_TOKEN=a-long-random-string
```

```http
POST /send
Authorization: Bearer a-long-random-string
Content-Type: application/json

{"to": "+15555550101", "body": "Riverside Community Health: Spanish interpreter needed ..."}
```

Return any `2xx`. If the response is JSON with an `id`, Langdesk stores it as the provider
message ID.

**Inbound.** Forward replies to Langdesk:

```dotenv
LANGDESK_SMS_INBOUND_TOKEN=another-long-random-string
```

```http
POST /sms/inbound/
Authorization: Bearer another-long-random-string
Content-Type: application/json

{"from": "+15555550101", "body": "YES 2100"}
```

Langdesk answers `{"result": "accepted", "reply": ""}`. Any reply text (for example to `HELP`) is
also sent back through your outbound relay.

## Writing your own backend

A backend is a class with a `send(to, body)` method that returns the provider's message ID and
raises `langdesk.messaging.backends.SMSError` on failure:

```python
from langdesk.messaging.backends import BaseSMSBackend, SMSError


class MyProviderBackend(BaseSMSBackend):
    name = "myprovider"

    def send(self, to: str, body: str) -> str:
        ...
        return message_id
```

Point `LANGDESK_SMS_BACKEND` at its dotted path. Failed sends are retried by the worker and kept,
with the error, under **Admin → Notifications**.

## Trying it without a provider

The default console backend writes texts to the logs. With `LANGDESK_SMS_SIMULATOR=true`,
coordinators get an **SMS simulator** page that shows each interpreter's texts and lets you reply
as them, using the same parser as the real webhooks.
