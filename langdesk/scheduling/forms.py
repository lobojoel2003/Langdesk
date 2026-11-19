from __future__ import annotations

import datetime as dt

from django import forms
from django.utils import timezone

from langdesk.roster.models import Department, Interpreter, Language, Location

from .models import InterpreterRequest, Modality

DURATIONS = [
    (15, "15 min"),
    (30, "30 min"),
    (45, "45 min"),
    (60, "1 hr"),
    (90, "1½ hr"),
    (120, "2 hr"),
    (180, "3 hr"),
    (240, "4 hr"),
    (480, "Full day"),
]
GRACE = dt.timedelta(minutes=15)


def next_half_hour(now: dt.datetime | None = None) -> dt.datetime:
    local = timezone.localtime(now or timezone.now())
    rounded = local.replace(second=0, microsecond=0) + dt.timedelta(minutes=30)
    return rounded.replace(minute=0 if rounded.minute < 30 else 30)


class RequestForm(forms.ModelForm):
    """The 20-second request: language, when, where, in person or video."""

    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    start_time = forms.TimeField(
        label="Start", widget=forms.TimeInput(attrs={"type": "time", "step": 300})
    )
    duration = forms.TypedChoiceField(
        choices=DURATIONS, coerce=int, initial=60, widget=forms.RadioSelect
    )

    class Meta:
        model = InterpreterRequest
        fields = [
            "language",
            "modality",
            "location",
            "location_detail",
            "service_type",
            "department",
            "appointment_ref",
            "notes",
        ]
        widgets = {
            "modality": forms.RadioSelect,
            "notes": forms.Textarea(attrs={"rows": 2, "maxlength": 280}),
            "appointment_ref": forms.TextInput(
                attrs={"placeholder": "e.g. APPT-48213", "autocomplete": "off"}
            ),
            "location_detail": forms.TextInput(attrs={"placeholder": "e.g. Room 3, 2nd floor"}),
        }

    def __init__(self, *args, user=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["language"].queryset = Language.objects.filter(is_active=True)
        self.fields["language"].empty_label = "Choose a language"
        self.fields["location"].queryset = Location.objects.filter(is_active=True)
        self.fields["location"].empty_label = "Choose a site"
        self.fields["department"].queryset = Department.objects.filter(is_active=True)
        self.fields["department"].empty_label = "None"
        self.fields["modality"].choices = Modality.choices
        self.fields["modality"].initial = Modality.IN_PERSON

        instance = self.instance
        if instance.pk:
            start = timezone.localtime(instance.starts_at)
            self.initial.update(
                date=start.date(),
                start_time=start.time().replace(second=0, microsecond=0),
                duration=instance.duration_minutes,
            )
            if instance.duration_minutes not in dict(DURATIONS):
                self.fields["duration"].choices = [
                    *DURATIONS,
                    (instance.duration_minutes, f"{instance.duration_minutes} min"),
                ]
        else:
            start = next_half_hour()
            self.initial.setdefault("date", start.date())
            self.initial.setdefault("start_time", start.time())
            if user is not None and user.is_authenticated:
                last = (
                    InterpreterRequest.objects.filter(requested_by=user)
                    .order_by("-created_at")
                    .values("location", "department", "service_type")
                    .first()
                )
                if last:
                    self.initial.setdefault("location", last["location"])
                    self.initial.setdefault("department", last["department"])
                    self.initial.setdefault("service_type", last["service_type"])

    def clean(self) -> dict:
        data = super().clean()
        date, start_time, duration = data.get("date"), data.get("start_time"), data.get("duration")
        if date and start_time and duration:
            starts_at = timezone.make_aware(dt.datetime.combine(date, start_time))
            moved = not self.instance.pk or starts_at != self.instance.starts_at
            if moved and starts_at < timezone.now() - GRACE:
                self.add_error("start_time", "That time has already passed.")
            self.instance.starts_at = starts_at
            self.instance.ends_at = starts_at + dt.timedelta(minutes=duration)

        modality, location = data.get("modality"), data.get("location")
        if modality == Modality.IN_PERSON and not location:
            self.add_error("location", "Choose where the interpreter should go.")
        language = data.get("language")
        if language and language.is_sign_language and modality == Modality.PHONE:
            self.add_error("modality", f"{language} can't be interpreted by phone.")
        return data

    @property
    def changed_fields(self) -> list[str]:
        """Model-level names of what changed, for the audit log."""
        mapping = {"date": "starts_at", "start_time": "starts_at", "duration": "ends_at"}
        changed = {mapping.get(name, name) for name in self.changed_data}
        return sorted(changed)


class InterpreterChoiceForm(forms.Form):
    interpreter = forms.ModelChoiceField(queryset=Interpreter.objects.active())


class ReasonForm(forms.Form):
    reason = forms.CharField(max_length=200, required=False)


class OutcomeForm(forms.Form):
    outcome = forms.ChoiceField(
        choices=InterpreterRequest.Outcome.choices, widget=forms.RadioSelect
    )
    actual_minutes = forms.IntegerField(
        label="Minutes interpreted", min_value=1, max_value=24 * 60, required=False
    )
    notes = forms.CharField(
        max_length=280,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        validators=InterpreterRequest._meta.get_field("outcome_notes").validators,
    )

    def __init__(self, *args, req: InterpreterRequest, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        Outcome = InterpreterRequest.Outcome
        if req.interpreter:
            allowed = [
                Outcome.COMPLETED,
                Outcome.CLIENT_NO_SHOW,
                Outcome.INTERPRETER_NO_SHOW,
                Outcome.CLIENT_DECLINED,
            ]
            self.fields["actual_minutes"].initial = req.duration_minutes
        else:
            allowed = [
                Outcome.UNFILLED,
                Outcome.VENDOR_LINE,
                Outcome.CLIENT_DECLINED,
                Outcome.CLIENT_NO_SHOW,
            ]
        self.fields["outcome"].choices = [(o.value, o.label) for o in allowed]
        self.fields["outcome"].initial = allowed[0].value
