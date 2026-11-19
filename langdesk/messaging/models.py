"""Every message Langdesk sends or receives, kept for the audit log."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class Channel(models.TextChoices):
    SMS = "sms", "Text message"
    EMAIL = "email", "Email"


class Notification(models.Model):
    class Kind(models.TextChoices):
        OFFER = "offer", "Offer"
        FILLED = "filled", "Offer withdrawn"
        CONFIRMATION = "confirmation", "Assignment confirmation"
        UPDATE = "update", "Assignment update"
        REMINDER = "reminder", "Reminder"
        CANCELLATION = "cancellation", "Cancellation"
        REQUESTER_UPDATE = "requester_update", "Requester update"
        COORDINATOR_ALERT = "coordinator_alert", "Coordinator alert"
        REPLY = "reply", "Reply to inbound text"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    channel = models.CharField(max_length=8, choices=Channel.choices)
    kind = models.CharField(max_length=24, choices=Kind.choices)
    to_address = models.CharField(max_length=254)
    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField()
    ics = models.TextField(blank=True, help_text="Calendar invite attached to the email.")
    request = models.ForeignKey(
        "scheduling.InterpreterRequest",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    interpreter = models.ForeignKey(
        "roster.Interpreter",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notifications",
    )
    recipient_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    dedupe_key = models.CharField(max_length=160, unique=True, null=True, blank=True)
    status = models.CharField(
        max_length=8, choices=Status.choices, default=Status.QUEUED, db_index=True
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    provider_id = models.CharField(max_length=120, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} via {self.channel} to {self.to_address}"


class InboundMessage(models.Model):
    class Result(models.TextChoices):
        ACCEPTED = "accepted", "Accepted an offer"
        DECLINED = "declined", "Declined an offer"
        ALREADY_FILLED = "filled", "Offer already filled"
        AMBIGUOUS = "ambiguous", "Needed a reply code"
        NO_OFFER = "no_offer", "No open offer"
        UNKNOWN_SENDER = "unknown_sender", "Unknown number"
        STOP = "stop", "Opted out"
        START = "start", "Opted back in"
        HELP = "help", "Asked for help"
        UNRECOGNISED = "unrecognised", "Not understood"

    channel = models.CharField(max_length=8, choices=Channel.choices, default=Channel.SMS)
    from_address = models.CharField(max_length=254)
    body = models.TextField()
    interpreter = models.ForeignKey(
        "roster.Interpreter",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="inbound_messages",
    )
    offer = models.ForeignKey(
        "scheduling.Offer", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    result = models.CharField(max_length=16, choices=Result.choices)
    reply = models.TextField(blank=True)
    received_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-received_at", "-pk"]

    def __str__(self) -> str:
        return f"{self.from_address}: {self.body[:40]}"
