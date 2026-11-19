"""Interpreter requests, the offers sent for them, and their audit trail."""

from __future__ import annotations

import datetime as dt

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

from langdesk.core.tokens import offer_token
from langdesk.core.validators import appointment_ref_validator, validate_no_personal_details
from langdesk.roster.models import Department, Interpreter, Language, Location


class Modality(models.TextChoices):
    IN_PERSON = "in_person", "In person"
    VIDEO = "video", "Video"
    PHONE = "phone", "Phone"


class ServiceType(models.TextChoices):
    MEDICAL = "medical", "Medical"
    BEHAVIORAL = "behavioral", "Behavioral health"
    EDUCATION = "education", "Education"
    LEGAL = "legal", "Legal"
    SOCIAL = "social", "Social services"
    OTHER = "other", "Other"


class RequestQuerySet(models.QuerySet["InterpreterRequest"]):
    def open(self) -> RequestQuerySet:
        return self.filter(status=InterpreterRequest.Status.OPEN)

    def assigned(self) -> RequestQuerySet:
        return self.filter(status=InterpreterRequest.Status.ASSIGNED)

    def upcoming(self, now: dt.datetime | None = None) -> RequestQuerySet:
        return self.filter(ends_at__gt=now or timezone.now())

    def needs_outcome(self, now: dt.datetime | None = None) -> RequestQuerySet:
        return self.filter(
            status__in=[InterpreterRequest.Status.OPEN, InterpreterRequest.Status.ASSIGNED],
            ends_at__lte=now or timezone.now(),
        )

    def visible_to(self, user) -> RequestQuerySet:
        from langdesk.core.roles import is_coordinator

        if is_coordinator(user):
            return self
        return self.filter(requested_by=user)


class InterpreterRequest(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ASSIGNED = "assigned", "Assigned"
        CLOSED = "closed", "Closed"
        CANCELLED = "cancelled", "Cancelled"

    class Outcome(models.TextChoices):
        COMPLETED = "completed", "Interpreted"
        CLIENT_NO_SHOW = "client_no_show", "Client did not attend"
        INTERPRETER_NO_SHOW = "interpreter_no_show", "Interpreter did not attend"
        CLIENT_DECLINED = "client_declined", "Client declined an interpreter"
        VENDOR_LINE = "vendor_line", "Covered by an outside phone or video line"
        UNFILLED = "unfilled", "No interpreter found"
        CANCELLED = "cancelled", "Appointment cancelled"

    #: Outcomes that count as language assistance having been provided.
    SERVED_OUTCOMES = frozenset({Outcome.COMPLETED, Outcome.VENDOR_LINE})

    reference = models.CharField(max_length=20, unique=True, editable=False, null=True)  # noqa: DJ001
    language = models.ForeignKey(Language, on_delete=models.PROTECT, related_name="requests")
    service_type = models.CharField(
        max_length=16, choices=ServiceType.choices, default=ServiceType.MEDICAL
    )
    modality = models.CharField(max_length=12, choices=Modality.choices)
    requested_modality = models.CharField(max_length=12, choices=Modality.choices)
    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField()
    location = models.ForeignKey(
        Location, null=True, blank=True, on_delete=models.PROTECT, related_name="requests"
    )
    location_detail = models.CharField(
        "Room or area", max_length=80, blank=True, validators=[validate_no_personal_details]
    )
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.PROTECT, related_name="requests"
    )
    appointment_ref = models.CharField(
        "Appointment reference",
        max_length=40,
        blank=True,
        db_index=True,
        validators=[appointment_ref_validator],
        help_text="Your scheduling system's appointment or case number. Never a name.",
    )
    notes = models.CharField(
        "Notes for the interpreter",
        max_length=280,
        blank=True,
        validators=[validate_no_personal_details],
        help_text="Logistics only. No names, birth dates or diagnoses.",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="interpreter_requests",
    )
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.OPEN, db_index=True
    )
    interpreter = models.ForeignKey(
        Interpreter, null=True, blank=True, on_delete=models.PROTECT, related_name="assignments"
    )
    assigned_at = models.DateTimeField(null=True, blank=True)
    video_url = models.URLField(blank=True)
    fell_back_to_video = models.BooleanField(default=False)
    outcome = models.CharField(max_length=24, choices=Outcome.choices, blank=True)
    outcome_notes = models.CharField(
        max_length=280, blank=True, validators=[validate_no_personal_details]
    )
    actual_minutes = models.PositiveIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(24 * 60)]
    )
    outcome_recorded_at = models.DateTimeField(null=True, blank=True)
    outcome_recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=200, blank=True)
    sequence = models.PositiveIntegerField(default=0, help_text="iCalendar SEQUENCE.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = RequestQuerySet.as_manager()

    class Meta:
        ordering = ["starts_at", "pk"]
        verbose_name = "interpreter request"
        indexes = [models.Index(fields=["status", "starts_at"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="request_ends_after_start",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.reference or 'New request'} · {self.language} · {self.starts_at:%Y-%m-%d}"

    def save(self, *args, **kwargs) -> None:
        if not self.requested_modality:
            self.requested_modality = self.modality
        super().save(*args, **kwargs)
        if not self.reference:
            self.reference = f"LD-{self.pk:05d}"
            type(self).objects.filter(pk=self.pk).update(reference=self.reference)

    def get_absolute_url(self) -> str:
        return reverse("scheduling:detail", args=[self.pk])

    # --- Derived state ------------------------------------------------------

    @property
    def duration_minutes(self) -> int:
        return int((self.ends_at - self.starts_at).total_seconds() // 60)

    @property
    def billable_minutes(self) -> int:
        return self.actual_minutes or self.duration_minutes

    @property
    def is_active(self) -> bool:
        return self.status in {self.Status.OPEN, self.Status.ASSIGNED}

    @property
    def has_started(self) -> bool:
        return self.starts_at <= timezone.now()

    @property
    def needs_outcome(self) -> bool:
        return self.is_active and self.ends_at <= timezone.now()

    @property
    def is_urgent(self) -> bool:
        return self.status == self.Status.OPEN and self.starts_at - timezone.now() < dt.timedelta(
            hours=24
        )

    @property
    def place(self) -> str:
        """Human description of where the interpreter is needed."""
        if self.modality == Modality.VIDEO:
            return "Video call"
        if self.modality == Modality.PHONE:
            return "Phone call"
        parts = [str(self.location) if self.location else "", self.location_detail]
        return ", ".join(part for part in parts if part)

    @property
    def served(self) -> bool:
        return self.outcome in self.SERVED_OUTCOMES

    def pending_offers(self) -> models.QuerySet[Offer]:
        return self.offers.filter(status=Offer.Status.PENDING)


class OfferQuerySet(models.QuerySet["Offer"]):
    def pending(self) -> OfferQuerySet:
        return self.filter(status=Offer.Status.PENDING)


class Offer(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Waiting for reply"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"
        EXPIRED = "expired", "No reply"
        WITHDRAWN = "withdrawn", "Withdrawn"

    request = models.ForeignKey(InterpreterRequest, on_delete=models.CASCADE, related_name="offers")
    interpreter = models.ForeignKey(Interpreter, on_delete=models.CASCADE, related_name="offers")
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    code = models.CharField(max_length=6, help_text="Reply code, e.g. YES 4821.")
    token = models.CharField(max_length=32, unique=True, default=offer_token, editable=False)
    score = models.IntegerField(default=0)
    reasons = models.JSONField(default=list, blank=True)
    wave = models.PositiveSmallIntegerField(default=1)
    sent_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    responded_at = models.DateTimeField(null=True, blank=True)
    response_channel = models.CharField(max_length=12, blank=True)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    objects = OfferQuerySet.as_manager()

    class Meta:
        ordering = ["-score", "sent_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["request", "interpreter"],
                condition=models.Q(status="pending"),
                name="one_pending_offer_per_person",
            )
        ]

    def __str__(self) -> str:
        return f"Offer {self.code} to {self.interpreter} for {self.request.reference}"

    def get_absolute_url(self) -> str:
        return reverse("scheduling:offer_respond", args=[self.token])


class RequestEvent(models.Model):
    class Kind(models.TextChoices):
        CREATED = "created", "Created"
        UPDATED = "updated", "Updated"
        OFFERED = "offered", "Offered"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"
        EXPIRED = "expired", "Offer expired"
        ASSIGNED = "assigned", "Assigned"
        UNASSIGNED = "unassigned", "Unassigned"
        VIDEO_FALLBACK = "video_fallback", "Switched to video"
        REMINDER = "reminder", "Reminder sent"
        ALERT = "alert", "Coordinator alerted"
        CANCELLED = "cancelled", "Cancelled"
        OUTCOME = "outcome", "Outcome recorded"

    request = models.ForeignKey(InterpreterRequest, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    message = models.CharField(max_length=255)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    interpreter = models.ForeignKey(
        Interpreter, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self) -> str:
        return f"{self.request.reference} {self.kind}: {self.message}"

    @property
    def actor_label(self) -> str:
        if self.actor:
            return self.actor.get_full_name() or self.actor.get_username()
        if self.interpreter:
            return self.interpreter.name
        return "Langdesk"
