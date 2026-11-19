"""Langdesk: interpreter scheduling for clinics, schools and legal aid offices."""

from .celery import app as celery_app
from .version import __version__

__all__ = ["__version__", "celery_app"]
