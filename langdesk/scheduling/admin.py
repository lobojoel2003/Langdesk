from django.contrib import admin
from django.db import models

from .models import InterpreterRequest, Offer, RequestEvent


class OfferInline(admin.TabularInline):
    model = Offer
    extra = 0
    can_delete = False
    fields = ["interpreter", "status", "code", "score", "wave", "sent_at", "responded_at"]
    readonly_fields = fields

    def has_add_permission(self, request, obj=None) -> bool:
        return False


class EventInline(admin.TabularInline):
    model = RequestEvent
    extra = 0
    can_delete = False
    fields = ["created_at", "kind", "message", "actor", "interpreter"]
    readonly_fields = fields

    def has_add_permission(self, request, obj=None) -> bool:
        return False


@admin.register(InterpreterRequest)
class InterpreterRequestAdmin(admin.ModelAdmin):
    list_display = [
        "reference",
        "language",
        "starts_at",
        "modality",
        "location",
        "status",
        "interpreter",
        "outcome",
    ]
    list_filter = ["status", "outcome", "modality", "language", "location", "service_type"]
    search_fields = ["reference", "appointment_ref", "interpreter__name"]
    date_hierarchy = "starts_at"
    list_select_related = ["language", "location", "interpreter"]
    inlines = [OfferInline, EventInline]
    formfield_overrides = {models.URLField: {"assume_scheme": "https"}}
    readonly_fields = [
        "reference",
        "requested_by",
        "assigned_at",
        "outcome_recorded_at",
        "outcome_recorded_by",
        "cancelled_at",
        "sequence",
        "created_at",
        "updated_at",
    ]

    def has_delete_permission(self, request, obj=None) -> bool:
        # The request history is the compliance record; cancel instead of deleting.
        return request.user.is_superuser


@admin.register(RequestEvent)
class RequestEventAdmin(admin.ModelAdmin):
    list_display = ["created_at", "request", "kind", "message", "actor", "interpreter"]
    list_filter = ["kind"]
    search_fields = ["request__reference", "message"]
    date_hierarchy = "created_at"

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
