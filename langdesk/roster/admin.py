from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import (
    AvailabilityWindow,
    Department,
    Interpreter,
    InterpreterLanguage,
    Language,
    Location,
    TimeOff,
)


@admin.register(Language)
class LanguageAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "native_name", "is_sign_language", "is_active", "roster"]
    list_filter = ["is_active", "is_sign_language"]
    search_fields = ["name", "code", "native_name"]

    @admin.display(description="Interpreters")
    def roster(self, obj: Language) -> int:
        return obj.skills.filter(interpreter__is_active=True).count()


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ["name", "address", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name", "address"]


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ["name", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name"]


class InterpreterLanguageInline(admin.TabularInline):
    model = InterpreterLanguage
    extra = 1
    autocomplete_fields = ["language"]


class AvailabilityInline(admin.TabularInline):
    model = AvailabilityWindow
    extra = 0


class TimeOffInline(admin.TabularInline):
    model = TimeOff
    extra = 0


@admin.register(Interpreter)
class InterpreterAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "employment",
        "language_list",
        "phone",
        "email",
        "modalities",
        "home_location",
        "is_active",
    ]
    list_filter = ["is_active", "employment", "languages", "home_location", "sms_opt_out"]
    search_fields = ["name", "email", "phone", "agency_name"]
    filter_horizontal = ["serves_locations"]
    inlines = [InterpreterLanguageInline, AvailabilityInline, TimeOffInline]
    readonly_fields = ["calendar_feed", "created_at", "updated_at"]
    actions = ["rotate_feed_tokens", "deactivate"]
    fieldsets = [
        (None, {"fields": ["name", "employment", "agency_name", "is_active"]}),
        ("Contact", {"fields": ["phone", "email", "preferred_channel", "sms_opt_out"]}),
        (
            "Work",
            {
                "fields": [
                    ("offers_in_person", "offers_video", "offers_phone"),
                    "home_location",
                    "serves_locations",
                    "max_daily_assignments",
                    "hourly_rate",
                ]
            },
        ),
        ("Calendar", {"fields": ["calendar_feed"]}),
        ("Internal", {"fields": ["notes", "created_at", "updated_at"]}),
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("languages")

    @admin.display(description="Languages")
    def language_list(self, obj: Interpreter) -> str:
        return ", ".join(language.name for language in obj.languages.all())

    @admin.display(description="Modes")
    def modalities(self, obj: Interpreter) -> str:
        modes = [
            label
            for enabled, label in [
                (obj.offers_in_person, "In person"),
                (obj.offers_video, "Video"),
                (obj.offers_phone, "Phone"),
            ]
            if enabled
        ]
        return " · ".join(modes)

    @admin.display(description="Subscribable calendar")
    def calendar_feed(self, obj: Interpreter) -> str:
        if not obj.pk:
            return "Available after saving."
        url = reverse("scheduling:feed", args=[obj.feed_token])
        return format_html('<a href="{0}">{0}</a>', url)

    @admin.action(description="Issue new calendar feed links")
    def rotate_feed_tokens(self, request, queryset) -> None:
        for interpreter in queryset:
            interpreter.rotate_feed_token()
        self.message_user(request, f"Issued new feed links for {queryset.count()} interpreter(s).")

    @admin.action(description="Deactivate selected interpreters")
    def deactivate(self, request, queryset) -> None:
        updated = queryset.update(is_active=False)
        self.message_user(request, f"Deactivated {updated} interpreter(s).")
