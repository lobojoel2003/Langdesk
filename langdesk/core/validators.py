"""Validators that keep protected personal information out of Langdesk.

Langdesk stores an appointment *reference*, never a client's name, date of birth or
diagnosis. These checks are a guard rail, not a guarantee, and are paired with clear
help text on every free-text field.
"""

from __future__ import annotations

import re

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

appointment_ref_validator = RegexValidator(
    regex=r"^[A-Za-z0-9][A-Za-z0-9\-_.#/:]{0,39}$",
    message=(
        "Use the appointment or case number only (letters, digits, - _ . # / :, no spaces). "
        "Do not enter names."
    ),
)

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "a Social Security number"),
    (
        re.compile(r"\b(?:0?[1-9]|1[0-2])[/-](?:0?[1-9]|[12]\d|3[01])[/-](?:19|20)\d{2}\b"),
        "a date of birth",
    ),
    (re.compile(r"\b(?:19|20)\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\b"), "a date"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "an email address"),
    (re.compile(r"(?:\+?\d[\s.()-]?){10,}"), "a phone number"),
    (re.compile(r"\b(?:DOB|D\.O\.B|MRN|SSN|diagnos\w*)\b", re.IGNORECASE), "client details"),
]


def validate_no_personal_details(value: str) -> None:
    for pattern, label in _PATTERNS:
        if pattern.search(value or ""):
            raise ValidationError(
                f"This looks like it contains {label}. Langdesk keeps client details out: "
                "describe logistics only (e.g. 'Check in at front desk').",
                code="personal_details",
            )
