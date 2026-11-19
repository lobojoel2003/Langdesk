"""Settings for the test suite. Uses Postgres when DATABASE_URL is set, SQLite otherwise."""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "langdesk-tests-only")
os.environ.setdefault("LANGDESK_BASE_URL", "https://langdesk.test")

from langdesk.settings import *  # noqa: F403
from langdesk.settings import LOGGING, STORAGES

DEBUG = False
ALLOWED_HOSTS = ["testserver", "langdesk.test"]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
STORAGES = {
    **STORAGES,
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
TIME_ZONE = "America/New_York"

CELERY_BROKER_URL = "memory://"
CELERY_TASK_ALWAYS_EAGER = True
LANGDESK_TASKS_EAGER = True

LANGDESK_ORG_NAME = "Test Clinic"
LANGDESK_SUPPORT_CONTACT = "Language access desk, ext. 4400"
LANGDESK_SMS_BACKEND = "langdesk.messaging.backends.locmem.LocMemSMSBackend"
LANGDESK_SMS_SIMULATOR = True
LANGDESK_AUTO_DISPATCH = True
LANGDESK_OFFER_WAVE_SIZE = 3
LANGDESK_OFFER_TIMEOUT_MINUTES = 20
LANGDESK_VIDEO_FALLBACK_MINUTES = 60
LANGDESK_REMINDER_MINUTES = [1440, 120]
LANGDESK_TRAVEL_BUFFER_MINUTES = 15
TWILIO_AUTH_TOKEN = "twilio-test-token"
LANGDESK_SMS_INBOUND_TOKEN = "inbound-test-token"

LOGGING = {**LOGGING, "root": {"handlers": ["console"], "level": "CRITICAL"}}
