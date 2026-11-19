"""Pluggable SMS backends, selected with ``LANGDESK_SMS_BACKEND``.

A backend is any class with a ``send(to, body) -> str`` method that returns the provider's
message id and raises :class:`SMSError` on failure.
"""

from functools import cache

from django.conf import settings
from django.utils.module_loading import import_string

from .base import BaseSMSBackend, SMSError

__all__ = ["BaseSMSBackend", "SMSError", "get_sms_backend"]


@cache
def _load(path: str) -> type[BaseSMSBackend]:
    return import_string(path)


def get_sms_backend() -> BaseSMSBackend:
    return _load(settings.LANGDESK_SMS_BACKEND)()
