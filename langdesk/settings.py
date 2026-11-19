"""Django settings for Langdesk.

Every deployment-specific value comes from an environment variable. See
``.env.example`` and ``docs/configuration.md`` for the full list.
"""

from __future__ import annotations

import os
from pathlib import Path

import dj_database_url
from celery.schedules import crontab
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be an integer, got {value!r}") from exc


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


# --- Core -------------------------------------------------------------------

DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "django-insecure-langdesk-development-only"
    else:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY is required when DJANGO_DEBUG is off. "
            "The Docker entrypoint generates one automatically."
        )

LANGDESK_BASE_URL = env("LANGDESK_BASE_URL", "http://localhost:8000").rstrip("/")

# localhost stays allowed so container health checks work behind any public hostname.
ALLOWED_HOSTS = [
    *env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]"),
    "localhost",
    "127.0.0.1",
]
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", LANGDESK_BASE_URL)

INSTALLED_APPS = [
    "langdesk.core",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "langdesk.roster",
    "langdesk.scheduling",
    "langdesk.messaging",
    "langdesk.reports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "langdesk.urls"
WSGI_APPLICATION = "langdesk.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "langdesk.core.context_processors.langdesk",
            ],
        },
    },
]

DATABASES = {
    "default": dj_database_url.parse(
        env("DATABASE_URL") or f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=env_int("DATABASE_CONN_MAX_AGE", 60),
        conn_health_checks=True,
    )
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"

# --- Internationalisation ---------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = env("LANGDESK_TIME_ZONE", "America/New_York")
USE_I18N = True
USE_TZ = True

# --- Static files -----------------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

# --- Security ---------------------------------------------------------------

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", False)
SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
SECURE_HSTS_SECONDS = env_int("DJANGO_SECURE_HSTS_SECONDS", 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", False)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_SECURE = env_bool(
    "DJANGO_SESSION_COOKIE_SECURE", LANGDESK_BASE_URL.startswith("https")
)
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = env_int("DJANGO_SESSION_COOKIE_AGE", 60 * 60 * 12)
X_FRAME_OPTIONS = "DENY"

# --- Email ------------------------------------------------------------------

EMAIL_BACKEND = env("DJANGO_EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "localhost")
EMAIL_PORT = env_int("EMAIL_PORT", 587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
EMAIL_TIMEOUT = env_int("EMAIL_TIMEOUT", 20)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "Langdesk <langdesk@localhost>")
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# --- Background jobs --------------------------------------------------------

CELERY_BROKER_URL = env("CELERY_BROKER_URL", env("REDIS_URL"))
CELERY_RESULT_BACKEND = None
CELERY_TASK_IGNORE_RESULT = True
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BEAT_SCHEDULE = {
    "dispatcher": {
        "task": "langdesk.scheduling.tasks.run_dispatcher",
        "schedule": 60.0,
    },
    "nightly-cleanup": {
        "task": "langdesk.scheduling.tasks.expire_stale_offers",
        "schedule": crontab(hour=3, minute=17),
    },
}

# Without a broker, run background work inline. Good for trials and tests.
LANGDESK_TASKS_EAGER = env_bool("LANGDESK_TASKS_EAGER", not CELERY_BROKER_URL)

# --- Langdesk ---------------------------------------------------------------

LANGDESK_ORG_NAME = env("LANGDESK_ORG_NAME", "Langdesk")
LANGDESK_SUPPORT_CONTACT = env("LANGDESK_SUPPORT_CONTACT")

LANGDESK_SMS_BACKEND = env(
    "LANGDESK_SMS_BACKEND", "langdesk.messaging.backends.console.ConsoleSMSBackend"
)
LANGDESK_SMS_SIMULATOR = env_bool("LANGDESK_SMS_SIMULATOR", DEBUG)
LANGDESK_DEFAULT_COUNTRY_CODE = env("LANGDESK_DEFAULT_COUNTRY_CODE", "1")

TWILIO_ACCOUNT_SID = env("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = env("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = env("TWILIO_FROM_NUMBER")
TWILIO_MESSAGING_SERVICE_SID = env("TWILIO_MESSAGING_SERVICE_SID")

LANGDESK_SMS_WEBHOOK_URL = env("LANGDESK_SMS_WEBHOOK_URL")
LANGDESK_SMS_WEBHOOK_TOKEN = env("LANGDESK_SMS_WEBHOOK_TOKEN")
LANGDESK_SMS_INBOUND_TOKEN = env("LANGDESK_SMS_INBOUND_TOKEN")

LANGDESK_JITSI_BASE_URL = env("LANGDESK_JITSI_BASE_URL", "https://meet.jit.si").rstrip("/")
LANGDESK_JITSI_ROOM_PREFIX = env("LANGDESK_JITSI_ROOM_PREFIX", "langdesk")

LANGDESK_AUTO_DISPATCH = env_bool("LANGDESK_AUTO_DISPATCH", True)
LANGDESK_OFFER_WAVE_SIZE = env_int("LANGDESK_OFFER_WAVE_SIZE", 3)
LANGDESK_OFFER_TIMEOUT_MINUTES = env_int("LANGDESK_OFFER_TIMEOUT_MINUTES", 20)
LANGDESK_VIDEO_FALLBACK_MINUTES = env_int("LANGDESK_VIDEO_FALLBACK_MINUTES", 60)
LANGDESK_TRAVEL_BUFFER_MINUTES = env_int("LANGDESK_TRAVEL_BUFFER_MINUTES", 15)
LANGDESK_REMINDER_MINUTES = [
    int(value) for value in env_list("LANGDESK_REMINDER_MINUTES", "1440,120")
]
LANGDESK_FEED_PAST_DAYS = env_int("LANGDESK_FEED_PAST_DAYS", 30)

# --- Logging ----------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
    },
    "root": {"handlers": ["console"], "level": env("LANGDESK_LOG_LEVEL", "INFO")},
    "loggers": {
        "django.db.backends": {"level": "WARNING"},
    },
}
