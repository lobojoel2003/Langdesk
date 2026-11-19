#!/bin/sh
# Langdesk container entrypoint.
#   web      migrate, then serve with gunicorn on :8000 (default)
#   worker   Celery worker: sends texts and emails
#   beat     Celery beat: runs the dispatcher every minute
#   manage   any manage.py command, e.g. `manage createsuperuser`
set -eu

DATA_DIR="${LANGDESK_DATA_DIR:-/app/data}"

# Without DJANGO_SECRET_KEY, generate one once and keep it on the shared data volume.
if [ -z "${DJANGO_SECRET_KEY:-}" ]; then
  KEY_FILE="$DATA_DIR/secret_key"
  if [ ! -s "$KEY_FILE" ]; then
    umask 077
    python -c "import secrets; print(secrets.token_urlsafe(50))" > "$KEY_FILE"
  fi
  DJANGO_SECRET_KEY="$(cat "$KEY_FILE")"
  export DJANGO_SECRET_KEY
fi

command="${1:-web}"
if [ "$#" -gt 0 ]; then shift; fi

case "$command" in
  web)
    python manage.py migrate --noinput
    exec gunicorn langdesk.wsgi:application \
      --bind "0.0.0.0:${PORT:-8000}" \
      --workers "${GUNICORN_WORKERS:-3}" \
      --timeout "${GUNICORN_TIMEOUT:-60}" \
      --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" \
      --access-logfile - \
      "$@"
    ;;
  worker)
    exec celery -A langdesk worker --loglevel "${CELERY_LOG_LEVEL:-INFO}" \
      --concurrency "${CELERY_CONCURRENCY:-2}" "$@"
    ;;
  beat)
    exec celery -A langdesk beat --loglevel "${CELERY_LOG_LEVEL:-INFO}" \
      --schedule "$DATA_DIR/celerybeat-schedule" "$@"
    ;;
  manage)
    exec python manage.py "$@"
    ;;
  *)
    exec "$command" "$@"
    ;;
esac
