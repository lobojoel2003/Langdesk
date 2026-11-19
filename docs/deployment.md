# Deploying Langdesk

Langdesk runs as five containers from one `docker-compose.yml`: Postgres, Redis, the web app
(gunicorn), a Celery worker that sends texts and emails, and Celery beat that runs the
dispatcher every minute. A small virtual machine with 1 vCPU and 2 GB of memory is plenty for a
clinic, school district or legal aid office.

## First start

```bash
mkdir langdesk && cd langdesk
```

```bash
curl -LO https://github.com/lobojoel2003/Langdesk/releases/latest/download/docker-compose.yml
```

```bash
curl -L -o .env https://github.com/lobojoel2003/Langdesk/releases/latest/download/env.example
```

Edit `.env`: at least `LANGDESK_ORG_NAME`, `LANGDESK_BASE_URL`, `LANGDESK_TIME_ZONE`,
`DJANGO_ALLOWED_HOSTS`, `POSTGRES_PASSWORD` and the email settings. Pin a release with
`LANGDESK_VERSION=1.0.0`. Then:

```bash
docker compose up -d
```

```bash
docker compose exec web langdesk-entrypoint manage createsuperuser
```

## Set up people

1. Sign in to **Admin** as the superuser.
2. Add your **Locations** (sites, with arrival instructions) and **Departments**.
3. Check **Languages**: 52 are preloaded; deactivate or add as needed.
4. Add **Interpreters** with their languages and credential level, phone and email, which modes
   they work (in person, video, phone), home site, sites they travel to, weekly hours and time
   off.
5. Add staff as **Users**. Put language access coordinators in the **Coordinators** group and
   tick *Staff status* so they can manage the roster in the admin. Everyone else can request
   interpreters and follow their own requests.
6. Send each interpreter their calendar link from their page under **Interpreters**.

## HTTPS

Put a reverse proxy in front of the web service. With [Caddy](https://caddyserver.com), add this
service to `docker-compose.yml` (or a `compose.override.yml`):

```yaml
  caddy:
    image: caddy:2
    restart: unless-stopped
    ports: ["80:80", "443:443"]
    command: caddy reverse-proxy --from langdesk.example.org --to web:8000
    volumes: [caddy-data:/data]
```

Add `caddy-data:` under `volumes:`, remove the `ports` from `web`, and set:

```dotenv
LANGDESK_BASE_URL=https://langdesk.example.org
DJANGO_ALLOWED_HOSTS=langdesk.example.org
DJANGO_SECURE_SSL_REDIRECT=true
DJANGO_SECURE_HSTS_SECONDS=31536000
```

## Backups

Everything that matters is in Postgres. Back it up daily:

```bash
docker compose exec -T db pg_dump -U langdesk -Fc langdesk > langdesk-$(date +%F).dump
```

Restore into a fresh stack:

```bash
docker compose exec -T db pg_restore -U langdesk -d langdesk --clean < langdesk-2026-11-19.dump
```

The `langdesk-data` volume holds the generated secret key and the beat schedule. If you lose it,
set `DJANGO_SECRET_KEY` explicitly; staff will need to sign in again.

## Upgrades

Read the [changelog](../CHANGELOG.md), back up, then:

```bash
docker compose pull
```

```bash
docker compose up -d
```

Migrations run automatically when the web container starts. Check the running version in the
page footer or at `/healthz`.

## Health checks and monitoring

`GET /healthz` returns `200` with `{"status": "ok", "database": "ok", "version": ..., "build": ...}`
when the app and database are up, and `503` otherwise. Compose uses it to order startup.

Failed texts and emails are kept under **Admin → Messages → Notifications** with the error, and
can be retried from there. Every request's page shows the messages sent for it.

## Running without Docker

Langdesk is a standard Django project. Install `requirements.txt` into a virtualenv, set
`DATABASE_URL` and `DJANGO_SECRET_KEY`, run `manage.py migrate` and `manage.py collectstatic`,
serve `langdesk.wsgi:application` with gunicorn, and run either Celery (`celery -A langdesk
worker` and `celery -A langdesk beat`) or, without Redis, `manage.py run_dispatcher --loop` as a
service.
