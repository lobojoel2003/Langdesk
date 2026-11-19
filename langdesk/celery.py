"""Celery application.

The worker runs queued notifications; beat runs the dispatcher once a minute. Without a
broker configured, Langdesk runs tasks inline so a single process is enough for trials.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "langdesk.settings")

app = Celery("langdesk")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
