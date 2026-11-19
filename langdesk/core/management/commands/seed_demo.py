"""Load a realistic demo: three sites, a mixed roster, a year of history and a live board.

All people, phone numbers (555-01xx) and addresses are fictional.
"""

from __future__ import annotations

import datetime as dt
import random

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.test.utils import override_settings
from django.utils import timezone

from langdesk.core.roles import COORDINATORS, REQUESTERS
from langdesk.roster.models import (
    AvailabilityWindow,
    Department,
    Interpreter,
    InterpreterLanguage,
    Language,
    Location,
    TimeOff,
)
from langdesk.scheduling.models import (
    InterpreterRequest,
    Modality,
    Offer,
    RequestEvent,
    ServiceType,
)
from langdesk.scheduling.services import dispatch
from langdesk.scheduling.video import new_video_link

Outcome = InterpreterRequest.Outcome
Status = InterpreterRequest.Status
CERT = InterpreterLanguage.Credential.CERTIFIED
QUAL = InterpreterLanguage.Credential.QUALIFIED

SITES = [
    (
        "Riverside Community Clinic",
        "1200 River Road\nSpringfield",
        "Check in at the front desk on level 1; interpreter badges are at registration.",
    ),
    (
        "Lincoln Elementary School",
        "45 Maple Avenue\nSpringfield",
        "Sign in at the main office. Visitor parking is behind the gym.",
    ),
    (
        "Legal Aid · Downtown Office",
        "300 Main Street, Suite 400\nSpringfield",
        "Take the elevator to the 4th floor and ask for the intake desk.",
    ),
]
DEPARTMENTS = [
    ("Primary Care", ServiceType.MEDICAL, 0),
    ("Pediatrics", ServiceType.MEDICAL, 0),
    ("Behavioral Health", ServiceType.BEHAVIORAL, 0),
    ("Special Education", ServiceType.EDUCATION, 1),
    ("Family Engagement", ServiceType.EDUCATION, 1),
    ("Housing", ServiceType.LEGAL, 2),
    ("Family Law", ServiceType.LEGAL, 2),
]
# name, employment, agency, home site index, languages [(code, credential)], modes, phone
ROSTER = [
    ("Ana Ramírez", "staff", "", 0, [("es", CERT)], "ivp", "+15555550101"),
    ("Carmen Díaz", "staff", "", 1, [("es", CERT), ("pt", QUAL)], "ivp", "+15555550102"),
    ("Luis Moreno", "contractor", "", None, [("es", QUAL)], "ivp", "+15555550103"),
    ("Mei Chen", "staff", "", 0, [("cmn", CERT), ("yue", CERT)], "ivp", "+15555550104"),
    ("Duc Nguyen", "contractor", "", None, [("vi", QUAL)], "ivp", "+15555550105"),
    (
        "Fatima Haidari",
        "contractor",
        "",
        2,
        [("prs", QUAL), ("ps", QUAL), ("fa", QUAL)],
        "ivp",
        "+15555550106",
    ),
    (
        "Amina Yusuf",
        "agency",
        "Lakeside Language Services",
        None,
        [("so", CERT), ("ar", QUAL)],
        "vp",
        "+15555550107",
    ),
    (
        "Jean-Baptiste Pierre",
        "contractor",
        "",
        None,
        [("ht", QUAL), ("fr", QUAL)],
        "ivp",
        "+15555550108",
    ),
    (
        "Olena Kovalenko",
        "contractor",
        "",
        None,
        [("uk", QUAL), ("ru", CERT)],
        "ivp",
        "+15555550109",
    ),
    ("Ji-woo Park", "contractor", "", None, [("ko", CERT)], "iv", "+15555550110"),
    ("Daniel Brooks", "contractor", "", None, [("ase", CERT)], "iv", "+15555550111"),
    ("Rosa Tzoc", "contractor", "", None, [("quc", QUAL), ("es", QUAL)], "ivp", "+15555550112"),
    (
        "Hana Abdi",
        "agency",
        "Lakeside Language Services",
        None,
        [("ar", CERT), ("so", QUAL)],
        "vp",
        "+15555550113",
    ),
    ("Sofia Alves", "staff", "", 0, [("pt", CERT), ("es", QUAL)], "ivp", "+15555550114"),
]
LANGUAGE_WEIGHTS = {
    "es": 44, "cmn": 8, "vi": 7, "ar": 6, "so": 5, "ht": 5, "yue": 4, "prs": 4,
    "uk": 4, "ko": 3, "pt": 3, "ase": 3, "quc": 2, "ru": 2,
}  # fmt: skip
OUTCOME_WEIGHTS = {
    Outcome.COMPLETED: 79, Outcome.CLIENT_NO_SHOW: 6, Outcome.CANCELLED: 6, Outcome.UNFILLED: 3,
    Outcome.VENDOR_LINE: 3, Outcome.CLIENT_DECLINED: 2, Outcome.INTERPRETER_NO_SHOW: 1,
}  # fmt: skip


class Command(BaseCommand):
    help = "Load demo users, roster, a year of history and a live board. Fictional data only."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--password", default="langdesk-demo")
        parser.add_argument("--history", type=int, default=320, help="Past requests to create.")
        parser.add_argument("--seed", type=int, default=2026)
        parser.add_argument(
            "--force", action="store_true", help="Run even if requests already exist."
        )

    def handle(self, *args, password: str, history: int, seed: int, force: bool, **options):
        if InterpreterRequest.objects.exists() and not force:
            raise CommandError("Requests already exist. Use --force to add demo data anyway.")
        self.rng = random.Random(seed)
        with transaction.atomic(), override_settings(LANGDESK_AUTO_DISPATCH=False):
            users = self._users(password)
            sites, departments = self._places()
            roster = self._roster(sites)
            self._history(history, users, sites, departments, roster)
        self._live(users, sites, departments)
        self.stdout.write(self.style.SUCCESS("Demo data loaded."))
        self.stdout.write(
            f"Sign in as 'coordinator', 'nurse.kim', 'ms.ortiz' or 'admin' "
            f"with password '{password}'."
        )

    # --- People and places -------------------------------------------------

    def _users(self, password: str) -> dict:
        User = get_user_model()
        coordinators = Group.objects.get_or_create(name=COORDINATORS)[0]
        requesters = Group.objects.get_or_create(name=REQUESTERS)[0]
        spec = [
            ("admin", "Avery", "Admin", True, None),
            ("coordinator", "Jordan", "Lee", False, coordinators),
            ("nurse.kim", "Grace", "Kim", False, requesters),
            ("ms.ortiz", "Elena", "Ortiz", False, requesters),
            ("paralegal.james", "Marcus", "James", False, requesters),
        ]
        users = {}
        for username, first, last, superuser, group in spec:
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "email": f"{username}@example.org",
                    "is_staff": superuser or group == coordinators,
                    "is_superuser": superuser,
                },
            )
            user.set_password(password)
            user.save()
            if group:
                user.groups.add(group)
            users[username] = user
        return users

    def _places(self):
        sites = [
            Location.objects.get_or_create(
                name=name, defaults={"address": address, "arrival_instructions": arrival}
            )[0]
            for name, address, arrival in SITES
        ]
        departments = [
            (Department.objects.get_or_create(name=name)[0], service, sites[site])
            for name, service, site in DEPARTMENTS
        ]
        return sites, departments

    def _roster(self, sites) -> list[Interpreter]:
        people = []
        for name, employment, agency, home, skills, modes, phone in ROSTER:
            person, created = Interpreter.objects.get_or_create(
                name=name,
                defaults={
                    "employment": employment,
                    "agency_name": agency,
                    "phone": phone,
                    "email": f"{name.split()[0].lower()}@interpreters.example.org",
                    "home_location": sites[home] if home is not None else None,
                    "offers_in_person": "i" in modes,
                    "offers_video": "v" in modes,
                    "offers_phone": "p" in modes,
                    "hourly_rate": None if employment == "staff" else 55 + 5 * len(people) % 30,
                },
            )
            if created:
                for code, credential in skills:
                    InterpreterLanguage.objects.create(
                        interpreter=person,
                        language=Language.objects.get(code=code),
                        credential=credential,
                        credential_detail="CCHI CoreCHI" if credential == CERT else "",
                    )
                if employment == "staff":
                    for weekday in range(5):
                        AvailabilityWindow.objects.create(
                            interpreter=person,
                            weekday=weekday,
                            start_time=dt.time(8, 0),
                            end_time=dt.time(17, 0),
                        )
            people.append(person)
        # One contractor is away next week, which shows up in the ranking.
        luis = people[2]
        start = timezone.now() + dt.timedelta(days=4)
        TimeOff.objects.get_or_create(
            interpreter=luis,
            starts_at=start,
            defaults={"ends_at": start + dt.timedelta(days=5), "reason": "Vacation"},
        )
        return people

    # --- A year of history -------------------------------------------------

    def _pick(self, weights: dict):
        keys = list(weights)
        return self.rng.choices(keys, weights=[weights[k] for k in keys])[0]

    def _history(self, count: int, users, sites, departments, roster) -> None:
        now = timezone.now()
        today = timezone.localdate()
        start_day = dt.date(today.year, 1, 2)
        span = (today - dt.timedelta(days=1) - start_day).days
        languages = {lang.code: lang for lang in Language.objects.filter(code__in=LANGUAGE_WEIGHTS)}
        speakers = {
            code: [p for p in roster if p.language_skills.filter(language__code=code).exists()]
            for code in LANGUAGE_WEIGHTS
        }
        requesters = [users["nurse.kim"], users["ms.ortiz"], users["paralegal.james"]]
        events, offers = [], []

        for _ in range(count):
            # Later months are a little busier, as programmes grow.
            offset = int(span * (self.rng.random() ** 0.85))
            day = start_day + dt.timedelta(days=offset)
            while day.weekday() >= 5:
                day -= dt.timedelta(days=1)
            minute = self.rng.choice(range(8 * 60, 16 * 60 + 1, 15))
            starts = timezone.make_aware(
                dt.datetime.combine(day, dt.time(minute // 60, minute % 60))
            )
            length = self.rng.choice([30, 45, 60, 60, 60, 90, 120])
            code = self._pick(LANGUAGE_WEIGHTS)
            department, service, site = self.rng.choice(departments)
            requester = requesters[sites.index(site)]
            modality = self.rng.choices(
                [Modality.IN_PERSON, Modality.VIDEO, Modality.PHONE], weights=[60, 30, 10]
            )[0]
            if code == "ase" and modality == Modality.PHONE:
                modality = Modality.VIDEO
            outcome = self._pick(OUTCOME_WEIGHTS)
            created = starts - dt.timedelta(
                hours=self.rng.choice([3, 20, 26, 50, 75, 120, 170, 240])
            )
            fell_back = modality == Modality.IN_PERSON and self.rng.random() < 0.05

            interpreter = None
            if outcome not in {Outcome.UNFILLED, Outcome.VENDOR_LINE, Outcome.CANCELLED} or (
                outcome == Outcome.CANCELLED and self.rng.random() < 0.5
            ):
                pool = [
                    p
                    for p in speakers[code]
                    if p.supports(Modality.VIDEO if fell_back else modality)
                ]
                interpreter = self.rng.choice(pool) if pool else None
                if interpreter is None and outcome in {
                    Outcome.COMPLETED,
                    Outcome.INTERPRETER_NO_SHOW,
                }:
                    outcome = Outcome.VENDOR_LINE
            assigned = created + dt.timedelta(minutes=self.rng.choice([4, 9, 15, 22, 35, 60, 140]))
            req = InterpreterRequest.objects.create(
                language=languages[code],
                service_type=service,
                modality=Modality.VIDEO if fell_back else modality,
                requested_modality=modality,
                starts_at=starts,
                ends_at=starts + dt.timedelta(minutes=length),
                location=site,
                location_detail=self.rng.choice(["", "", "Room 2", "Room 5", "Conference room B"]),
                department=department,
                appointment_ref=f"APPT-{self.rng.randint(10000, 99999)}",
                requested_by=requester,
                status=Status.CANCELLED if outcome == Outcome.CANCELLED else Status.CLOSED,
                interpreter=interpreter,
                assigned_at=assigned if interpreter else None,
                video_url=new_video_link() if fell_back or modality == Modality.VIDEO else "",
                fell_back_to_video=fell_back,
                outcome=outcome,
                actual_minutes=length if outcome == Outcome.COMPLETED else None,
                outcome_recorded_at=min(starts + dt.timedelta(minutes=length + 30), now),
                outcome_recorded_by=requester,
                cancelled_at=starts - dt.timedelta(hours=4)
                if outcome == Outcome.CANCELLED
                else None,
                cancel_reason="Appointment rescheduled" if outcome == Outcome.CANCELLED else "",
            )
            InterpreterRequest.objects.filter(pk=req.pk).update(created_at=created)
            events.append(
                RequestEvent(
                    request=req,
                    kind="created",
                    message=f"Requested {req.language}",
                    actor=requester,
                    created_at=created,
                )
            )
            others = [p for p in speakers[code] if p != interpreter]
            if others and self.rng.random() < 0.45:
                other = self.rng.choice(others)
                status = self.rng.choice([Offer.Status.DECLINED, Offer.Status.EXPIRED])
                offers.append(
                    Offer(
                        request=req,
                        interpreter=other,
                        status=status,
                        code=f"{self.rng.randint(1000, 9999)}",
                        expires_at=created + dt.timedelta(minutes=20),
                        sent_at=created,
                        responded_at=created + dt.timedelta(minutes=6)
                        if status == Offer.Status.DECLINED
                        else None,
                        response_channel="sms" if status == Offer.Status.DECLINED else "",
                    )
                )
            if interpreter:
                offers.append(
                    Offer(
                        request=req,
                        interpreter=interpreter,
                        status=Offer.Status.ACCEPTED,
                        code=f"{self.rng.randint(1000, 9999)}",
                        expires_at=assigned + dt.timedelta(minutes=20),
                        sent_at=created,
                        responded_at=assigned,
                        response_channel=self.rng.choice(["sms", "sms", "sms", "web"]),
                    )
                )
                events.append(
                    RequestEvent(
                        request=req,
                        kind="assigned",
                        message=f"{interpreter.name} assigned from an offer",
                        interpreter=interpreter,
                        created_at=assigned,
                    )
                )
            events.append(
                RequestEvent(
                    request=req,
                    kind="outcome",
                    message=f"Outcome: {req.get_outcome_display()}",
                    actor=requester,
                    created_at=req.outcome_recorded_at,
                )
            )
        Offer.objects.bulk_create(offers)
        RequestEvent.objects.bulk_create(events)

    # --- Live board ---------------------------------------------------------

    def _live(self, users, sites, departments) -> None:
        clinic, school, legal = sites
        dept = {d.name: d for d, _, _ in departments}
        now = timezone.localtime()
        today = now.date()

        def at(days: int, hour: int, minute: int = 0) -> dt.datetime:
            day = today + dt.timedelta(days=days)
            while day.weekday() >= 5:
                day += dt.timedelta(days=1)
            return timezone.make_aware(dt.datetime.combine(day, dt.time(hour, minute)))

        soon = (now + dt.timedelta(hours=3)).replace(minute=0, second=0, microsecond=0)
        plan = [
            # (language, start, minutes, modality, site, detail, department, requester, auto, ref)
            (
                "es",
                soon,
                60,
                Modality.IN_PERSON,
                clinic,
                "Room 3",
                "Pediatrics",
                "nurse.kim",
                True,
                "APPT-48213",
            ),
            (
                "prs",
                at(1, 10),
                90,
                Modality.IN_PERSON,
                legal,
                "Intake desk",
                "Housing",
                "paralegal.james",
                False,
                "CASE-2026-0412",
            ),
            (
                "so",
                at(1, 13, 30),
                60,
                Modality.VIDEO,
                clinic,
                "",
                "Primary Care",
                "nurse.kim",
                True,
                "APPT-48377",
            ),
            (
                "vi",
                at(2, 9),
                60,
                Modality.IN_PERSON,
                clinic,
                "Room 5",
                "Primary Care",
                "nurse.kim",
                False,
                "APPT-48402",
            ),
            (
                "ase",
                at(2, 15),
                120,
                Modality.IN_PERSON,
                school,
                "Library",
                "Special Education",
                "ms.ortiz",
                False,
                "IEP-2291",
            ),
            (
                "mam",
                at(3, 11),
                60,
                Modality.IN_PERSON,
                legal,
                "",
                "Family Law",
                "paralegal.james",
                False,
                "CASE-2026-0433",
            ),
            (
                "es",
                at(3, 16),
                45,
                Modality.IN_PERSON,
                school,
                "Room 12",
                "Family Engagement",
                "ms.ortiz",
                False,
                "CONF-118",
            ),
        ]
        created = []
        for code, start, minutes, modality, site, detail, department, who, auto, ref in plan:
            req = InterpreterRequest(
                language=Language.objects.get(code=code),
                service_type=next(s for d, s, _ in departments if d.name == department),
                modality=modality,
                starts_at=start,
                ends_at=start + dt.timedelta(minutes=minutes),
                location=site,
                location_detail=detail,
                department=dept[department],
                appointment_ref=ref,
            )
            with override_settings(LANGDESK_AUTO_DISPATCH=auto):
                created.append(dispatch.create_request(req, users[who]))

        # Already covered: today and tomorrow.
        covered = [
            ("cmn", at(0, 14), 60, Modality.IN_PERSON, clinic, "Primary Care", "Mei Chen"),
            ("es", at(1, 9, 30), 60, Modality.IN_PERSON, clinic, "Pediatrics", "Ana Ramírez"),
            (
                "ht",
                at(1, 11),
                45,
                Modality.VIDEO,
                clinic,
                "Behavioral Health",
                "Jean-Baptiste Pierre",
            ),
            ("ko", at(1, 15), 60, Modality.IN_PERSON, legal, "Family Law", "Ji-woo Park"),
        ]
        for code, start, minutes, modality, site, department, name in covered:
            req = InterpreterRequest(
                language=Language.objects.get(code=code),
                modality=modality,
                starts_at=start,
                ends_at=start + dt.timedelta(minutes=minutes),
                location=site,
                department=dept[department],
                appointment_ref=f"APPT-{self.rng.randint(48000, 48999)}",
            )
            with override_settings(LANGDESK_AUTO_DISPATCH=False):
                dispatch.create_request(req, users["nurse.kim"])
            dispatch.assign(req, Interpreter.objects.get(name=name), users["coordinator"])

        # Finished but no outcome yet.
        for code, hours_ago, name in [("es", 26, "Luis Moreno"), ("uk", 5, "Olena Kovalenko")]:
            start = (now - dt.timedelta(hours=hours_ago)).replace(minute=0, second=0, microsecond=0)
            req = InterpreterRequest.objects.create(
                language=Language.objects.get(code=code),
                modality=Modality.IN_PERSON,
                requested_modality=Modality.IN_PERSON,
                starts_at=start,
                ends_at=start + dt.timedelta(hours=1),
                location=clinic,
                department=dept["Primary Care"],
                appointment_ref=f"APPT-{self.rng.randint(47000, 47999)}",
                requested_by=users["nurse.kim"],
                status=Status.ASSIGNED,
                interpreter=Interpreter.objects.get(name=name),
                assigned_at=start - dt.timedelta(days=1),
            )
            dispatch.log(req, RequestEvent.Kind.ASSIGNED, f"{name} assigned from an offer")

        # One interpreter has already said no to the urgent request, by text.
        from langdesk.messaging.inbound import handle_sms

        pending = list(created[0].pending_offers().select_related("interpreter"))
        if len(pending) > 1:
            offer = pending[-1]
            handle_sms(offer.interpreter.phone, f"no {offer.code} sorry, booked all afternoon")
