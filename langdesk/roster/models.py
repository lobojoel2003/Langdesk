"""The interpreter roster: languages, places, people and when they can work."""

from __future__ import annotations

import datetime as dt

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from langdesk.core.phone import normalize_phone, validate_phone
from langdesk.core.tokens import feed_token


class Language(models.Model):
    code = models.CharField(
        max_length=16, unique=True, help_text="BCP 47 tag, e.g. es, zh-yue, ase (ASL)."
    )
    name = models.CharField(max_length=80, unique=True)
    native_name = models.CharField(max_length=80, blank=True)
    is_sign_language = models.BooleanField(
        default=False, help_text="Sign languages cannot be interpreted by phone."
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Location(models.Model):
    name = models.CharField(max_length=120, unique=True)
    address = models.TextField(blank=True)
    arrival_instructions = models.TextField(
        blank=True, help_text="Where interpreters check in, parking, badge pickup."
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Department(models.Model):
    name = models.CharField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class InterpreterQuerySet(models.QuerySet["Interpreter"]):
    def active(self) -> InterpreterQuerySet:
        return self.filter(is_active=True)


class Interpreter(models.Model):
    class Employment(models.TextChoices):
        STAFF = "staff", "Staff"
        CONTRACTOR = "contractor", "Contractor"
        AGENCY = "agency", "Agency"

    class Channel(models.TextChoices):
        SMS = "sms", "Text message"
        EMAIL = "email", "Email"
        BOTH = "both", "Text and email"

    name = models.CharField(max_length=120)
    employment = models.CharField(
        max_length=12, choices=Employment.choices, default=Employment.STAFF
    )
    agency_name = models.CharField(max_length=120, blank=True)
    phone = models.CharField(
        max_length=20,
        blank=True,
        validators=[validate_phone],
        help_text="Mobile number for offers and replies. Stored in +15551234567 form.",
    )
    email = models.EmailField(blank=True)
    preferred_channel = models.CharField(
        max_length=8, choices=Channel.choices, default=Channel.BOTH
    )
    sms_opt_out = models.BooleanField(
        default=False, help_text="Set automatically when the interpreter texts STOP."
    )
    languages = models.ManyToManyField(
        Language, through="InterpreterLanguage", related_name="interpreters"
    )
    offers_in_person = models.BooleanField("In person", default=True)
    offers_video = models.BooleanField("Video", default=True)
    offers_phone = models.BooleanField("Phone", default=True)
    home_location = models.ForeignKey(
        Location,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="based_interpreters",
    )
    serves_locations = models.ManyToManyField(
        Location,
        blank=True,
        related_name="visiting_interpreters",
        help_text="Sites this interpreter travels to in person. Leave empty for any site.",
    )
    max_daily_assignments = models.PositiveSmallIntegerField(null=True, blank=True)
    hourly_rate = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True, help_text="Internal notes. Not shared.")
    feed_token = models.CharField(max_length=64, unique=True, default=feed_token, editable=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = InterpreterQuerySet.as_manager()

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs) -> None:
        self.phone = normalize_phone(self.phone)
        super().save(*args, **kwargs)

    def clean(self) -> None:
        self.phone = normalize_phone(self.phone)
        if not self.phone and not self.email:
            raise ValidationError("Add a mobile number or an email so offers can reach them.")
        if self.employment == self.Employment.AGENCY and not self.agency_name:
            raise ValidationError({"agency_name": "Name the agency for agency interpreters."})

    @property
    def short_name(self) -> str:
        """``Ana Ramírez`` becomes ``Ana R.``, used in messages to requesters."""
        parts = self.name.split()
        if len(parts) < 2:
            return self.name
        return f"{parts[0]} {parts[-1][0]}."

    @property
    def initials(self) -> str:
        parts = [p for p in self.name.split() if p]
        return "".join(p[0] for p in parts[:2]).upper()

    @property
    def can_text(self) -> bool:
        return bool(self.phone) and not self.sms_opt_out

    def wants(self, channel: str) -> bool:
        """Whether to contact this interpreter on ``channel``, falling back when needed."""
        if channel == self.Channel.SMS:
            return self.can_text and (
                self.preferred_channel != self.Channel.EMAIL or not self.email
            )
        return bool(self.email) and (
            self.preferred_channel != self.Channel.SMS or not self.can_text
        )

    def supports(self, modality: str) -> bool:
        return {
            "in_person": self.offers_in_person,
            "video": self.offers_video,
            "phone": self.offers_phone,
        }.get(modality, False)

    def rotate_feed_token(self) -> None:
        self.feed_token = feed_token()
        self.save(update_fields=["feed_token", "updated_at"])


class InterpreterLanguage(models.Model):
    class Credential(models.TextChoices):
        CERTIFIED = "certified", "Certified"
        QUALIFIED = "qualified", "Qualified"

    interpreter = models.ForeignKey(
        Interpreter, on_delete=models.CASCADE, related_name="language_skills"
    )
    language = models.ForeignKey(Language, on_delete=models.PROTECT, related_name="skills")
    credential = models.CharField(
        max_length=12,
        choices=Credential.choices,
        default=Credential.QUALIFIED,
        help_text="Certified: CCHI, NBCMI, court or state certification. "
        "Qualified: assessed for proficiency and trained in interpreter ethics.",
    )
    credential_detail = models.CharField(
        max_length=120, blank=True, help_text="e.g. CCHI CHI-Spanish #12345"
    )
    credential_expires = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["interpreter", "language"], name="unique_skill")
        ]
        ordering = ["language__name"]

    def __str__(self) -> str:
        return f"{self.interpreter} - {self.language} ({self.get_credential_display()})"

    @property
    def is_expired(self) -> bool:
        return bool(self.credential_expires and self.credential_expires < timezone.localdate())

    @property
    def effective_credential(self) -> str:
        if self.credential == self.Credential.CERTIFIED and self.is_expired:
            return self.Credential.QUALIFIED
        return self.credential


class AvailabilityWindow(models.Model):
    class Weekday(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"
        SATURDAY = 5, "Saturday"
        SUNDAY = 6, "Sunday"

    interpreter = models.ForeignKey(
        Interpreter, on_delete=models.CASCADE, related_name="availability"
    )
    weekday = models.PositiveSmallIntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        ordering = ["weekday", "start_time"]
        verbose_name_plural = "availability"

    def __str__(self) -> str:
        return f"{self.get_weekday_display()} {self.start_time:%H:%M}-{self.end_time:%H:%M}"

    def clean(self) -> None:
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValidationError("End time must be after start time.")

    def covers(self, start: dt.datetime, end: dt.datetime) -> bool:
        """True when the local ``start``-``end`` span sits inside this window."""
        local_start = timezone.localtime(start)
        local_end = timezone.localtime(end)
        if local_start.weekday() != self.weekday or local_end.date() != local_start.date():
            return False
        return self.start_time <= local_start.time() and local_end.time() <= self.end_time


class TimeOff(models.Model):
    interpreter = models.ForeignKey(Interpreter, on_delete=models.CASCADE, related_name="time_off")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    reason = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["starts_at"]
        verbose_name_plural = "time off"

    def __str__(self) -> str:
        return f"{self.interpreter}: {self.starts_at:%Y-%m-%d} to {self.ends_at:%Y-%m-%d}"

    def clean(self) -> None:
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValidationError("Time off must end after it starts.")
