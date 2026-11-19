from django.contrib import admin

from .models import InboundMessage, Notification
from .services import deliver


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["created_at", "kind", "channel", "to_address", "status", "request", "attempts"]
    list_filter = ["status", "channel", "kind"]
    search_fields = ["to_address", "subject", "body", "request__reference"]
    date_hierarchy = "created_at"
    readonly_fields = [field.name for field in Notification._meta.fields]
    actions = ["retry"]

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    @admin.action(description="Retry sending selected messages")
    def retry(self, request, queryset) -> None:
        sent = sum(
            deliver(pk) for pk in queryset.exclude(status="sent").values_list("pk", flat=True)
        )
        self.message_user(request, f"Re-sent {sent} message(s).")


@admin.register(InboundMessage)
class InboundMessageAdmin(admin.ModelAdmin):
    list_display = ["received_at", "from_address", "interpreter", "body", "result"]
    list_filter = ["result", "channel"]
    search_fields = ["from_address", "body", "interpreter__name"]
    date_hierarchy = "received_at"
    readonly_fields = [field.name for field in InboundMessage._meta.fields]

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False
