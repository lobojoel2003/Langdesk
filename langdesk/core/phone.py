"""Phone number normalisation.

Numbers are stored in E.164 form (``+15551234567``) so inbound texts can be matched to
interpreters. National numbers are prefixed with ``LANGDESK_DEFAULT_COUNTRY_CODE``.
"""

from __future__ import annotations

import re

from django.conf import settings
from django.core.exceptions import ValidationError

_DIGITS = re.compile(r"\d+")


def normalize_phone(raw: str | None) -> str:
    """Return ``raw`` as E.164, or an empty string when there is nothing to normalise."""
    if not raw:
        return ""
    value = raw.strip()
    digits = "".join(_DIGITS.findall(value))
    if not digits:
        return ""
    if value.startswith("+"):
        return f"+{digits}"
    if value.startswith("00"):
        return f"+{digits[2:]}"
    country = settings.LANGDESK_DEFAULT_COUNTRY_CODE
    if country == "1" and len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return f"+{country}{digits.lstrip('0')}"


def validate_phone(raw: str) -> None:
    normalized = normalize_phone(raw)
    digits = normalized[1:]
    if not 8 <= len(digits) <= 15:
        raise ValidationError("Enter a phone number with country code, e.g. +1 555 123 4567.")
