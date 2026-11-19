# Configuration reference

Langdesk reads all settings from environment variables. With Docker Compose, put them in a
`.env` file next to `docker-compose.yml` (start from [`.env.example`](../.env.example)).
Booleans accept `true/false`, `1/0`, `yes/no` or `on/off`.

## Organisation

| Variable | Default | Description |
|---|---|---|
| `LANGDESK_ORG_NAME` | `Langdesk` | Your organisation's name. Shown in the header and at the start of every text. |
| `LANGDESK_BASE_URL` | `http://localhost:8000` | The public URL of this server, without a trailing slash. Used in text and email links, calendar feeds, invite UIDs and Twilio signature checks. |
| `LANGDESK_TIME_ZONE` | `America/New_York` | IANA time zone for display, texts and reports. |
| `LANGDESK_SUPPORT_CONTACT` | | Shown in `HELP` replies, emails and the sign-in page, e.g. `Language access desk, ext. 4400`. |

## Django and security

| Variable | Default | Description |
|---|---|---|
| `DJANGO_SECRET_KEY` | generated | Required outside debug mode. The Docker entrypoint generates one on first start and stores it in the data volume. |
| `DJANGO_DEBUG` | `false` | Never enable in production. |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1,[::1]` | Comma-separated hostnames. `localhost` is always allowed for container health checks. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `LANGDESK_BASE_URL` | Extra origins allowed to submit forms. |
| `DJANGO_SECURE_SSL_REDIRECT` | `false` | Redirect HTTP to HTTPS. `/healthz` is exempt. |
| `DJANGO_SECURE_HSTS_SECONDS` | `0` | HSTS max-age. Use `31536000` once HTTPS works. |
| `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS` | `false` | |
| `DJANGO_SECURE_HSTS_PRELOAD` | `false` | |
| `DJANGO_SESSION_COOKIE_SECURE` | `true` if the base URL is HTTPS | |
| `DJANGO_SESSION_COOKIE_AGE` | `43200` | Seconds before staff are signed out (12 hours). |
| `LANGDESK_LOG_LEVEL` | `INFO` | |

## Database and background jobs

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | SQLite in the project folder | e.g. `postgres://user:pass@host:5432/langdesk`. Compose points this at its Postgres service. |
| `DATABASE_CONN_MAX_AGE` | `60` | Seconds to keep database connections open. |
| `POSTGRES_PASSWORD` | `langdesk` | Password for the bundled Postgres service (Compose only). |
| `CELERY_BROKER_URL` | `REDIS_URL` | e.g. `redis://redis:6379/0`. Without a broker, background work runs inline in the web process. |
| `LANGDESK_TASKS_EAGER` | `true` without a broker | Force inline delivery even with a broker. |

## Email

| Variable | Default | Description |
|---|---|---|
| `DJANGO_EMAIL_BACKEND` | console | `django.core.mail.backends.smtp.EmailBackend` for real email. |
| `EMAIL_HOST`, `EMAIL_PORT` | `localhost`, `587` | |
| `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | | |
| `EMAIL_USE_TLS`, `EMAIL_USE_SSL` | `true`, `false` | |
| `EMAIL_TIMEOUT` | `20` | Seconds. |
| `DEFAULT_FROM_EMAIL` | `Langdesk <langdesk@localhost>` | Sender and calendar invite organiser. |

## Text messages

See [sms.md](sms.md) for provider setup.

| Variable | Default | Description |
|---|---|---|
| `LANGDESK_SMS_BACKEND` | `langdesk.messaging.backends.console.ConsoleSMSBackend` | Or `...twilio.TwilioSMSBackend`, `...webhook.WebhookSMSBackend`, or your own class. |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` | | Twilio credentials. The auth token also verifies inbound webhooks. |
| `TWILIO_FROM_NUMBER` or `TWILIO_MESSAGING_SERVICE_SID` | | Sender. |
| `LANGDESK_SMS_WEBHOOK_URL`, `LANGDESK_SMS_WEBHOOK_TOKEN` | | Outbound relay for the webhook backend. |
| `LANGDESK_SMS_INBOUND_TOKEN` | | Bearer token required on `POST /sms/inbound/`. The endpoint is disabled until it's set. |
| `LANGDESK_SMS_SIMULATOR` | same as `DJANGO_DEBUG` | Shows the in-browser SMS simulator to coordinators. |
| `LANGDESK_DEFAULT_COUNTRY_CODE` | `1` | Prefix for phone numbers entered without a country code. |

## Dispatch rules

| Variable | Default | Description |
|---|---|---|
| `LANGDESK_AUTO_DISPATCH` | `true` | Offer new requests automatically. When off, coordinators offer from the board. |
| `LANGDESK_OFFER_WAVE_SIZE` | `3` | Interpreters per wave. The first to accept wins. |
| `LANGDESK_OFFER_TIMEOUT_MINUTES` | `20` | How long a wave waits before the next one goes out. |
| `LANGDESK_VIDEO_FALLBACK_MINUTES` | `60` | Minutes before start to switch unfilled in-person requests to video. `0` turns it off. |
| `LANGDESK_TRAVEL_BUFFER_MINUTES` | `15` | Gap required around in-person bookings. |
| `LANGDESK_REMINDER_MINUTES` | `1440,120` | Reminder lead times. Empty turns reminders off. |
| `LANGDESK_FEED_PAST_DAYS` | `30` | How far back calendar feeds go. |

## Video

| Variable | Default | Description |
|---|---|---|
| `LANGDESK_JITSI_BASE_URL` | `https://meet.jit.si` | Your Jitsi Meet server. |
| `LANGDESK_JITSI_ROOM_PREFIX` | `langdesk` | Room names are `<prefix>-<20 random hex characters>`. |

## Container

| Variable | Default | Description |
|---|---|---|
| `LANGDESK_VERSION` | `latest` | Image tag Compose runs: a release (`1.0.0`), `latest` or `edge`. |
| `LANGDESK_PORT` | `8000` | Host port for the web service. |
| `GUNICORN_WORKERS` | `3` | |
| `GUNICORN_TIMEOUT` | `60` | Seconds. |
| `FORWARDED_ALLOW_IPS` | `*` | Proxies trusted for `X-Forwarded-*` headers. |
| `CELERY_CONCURRENCY` | `2` | Worker processes. |
| `CELERY_LOG_LEVEL` | `INFO` | |
