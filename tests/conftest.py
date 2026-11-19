from __future__ import annotations

import datetime as dt
import itertools

import pytest
from django.contrib.auth.models import Group, User
from django.utils import timezone

from langdesk.core.roles import COORDINATORS
from langdesk.messaging.backends import locmem
from langdesk.roster.models import Interpreter, InterpreterLanguage, Language, Location
from langdesk.scheduling.models import InterpreterRequest, Modality

_phones = itertools.count(1)


@pytest.fixture(autouse=True)
def _clean_outbox():
    locmem.outbox.clear()
    yield
    locmem.outbox.clear()


@pytest.fixture
def sms():
    return locmem.outbox


@pytest.fixture
def make_user(db):
    def make(username: str, *, coordinator: bool = False, **fields) -> User:
        fields.setdefault("email", f"{username}@example.org")
        user = User.objects.create_user(username=username, password="pw", **fields)
        if coordinator:
            user.groups.add(Group.objects.get_or_create(name=COORDINATORS)[0])
        return user

    return make


@pytest.fixture
def coordinator(make_user) -> User:
    return make_user("coord", coordinator=True, first_name="Jordan", last_name="Lee")


@pytest.fixture
def requester(make_user) -> User:
    return make_user("nurse", first_name="Grace", last_name="Kim")


@pytest.fixture
def coordinator_client(client, coordinator):
    client.force_login(coordinator)
    return client


@pytest.fixture
def requester_client(client, requester):
    client.force_login(requester)
    return client


@pytest.fixture
def spanish(db) -> Language:
    return Language.objects.get(code="es")


@pytest.fixture
def asl(db) -> Language:
    return Language.objects.get(code="ase")


@pytest.fixture
def clinic(db) -> Location:
    return Location.objects.create(
        name="Main Clinic", address="1 Main St", arrival_instructions="Front desk"
    )


@pytest.fixture
def school(db) -> Location:
    return Location.objects.create(name="Lincoln School")


@pytest.fixture
def make_interpreter(db):
    def make(
        name: str,
        languages=(("es", InterpreterLanguage.Credential.QUALIFIED),),
        **fields,
    ) -> Interpreter:
        number = next(_phones)
        fields.setdefault("phone", f"+1555555{number:04d}")
        fields.setdefault("email", f"{name.split()[0].lower()}{number}@example.org")
        person = Interpreter.objects.create(name=name, **fields)
        for code, credential in languages:
            InterpreterLanguage.objects.create(
                interpreter=person, language=Language.objects.get(code=code), credential=credential
            )
        return person

    return make


@pytest.fixture
def make_request(db, spanish, clinic, requester):
    def make(
        *,
        starts_in: dt.timedelta = dt.timedelta(days=2),
        minutes: int = 60,
        starts_at: dt.datetime | None = None,
        **fields,
    ) -> InterpreterRequest:
        start = starts_at or (timezone.now() + starts_in).replace(second=0, microsecond=0)
        fields.setdefault("language", spanish)
        fields.setdefault("modality", Modality.IN_PERSON)
        fields.setdefault("location", clinic)
        fields.setdefault("requested_by", requester)
        return InterpreterRequest.objects.create(
            starts_at=start, ends_at=start + dt.timedelta(minutes=minutes), **fields
        )

    return make


def at_local(days: int, hour: int, minute: int = 0) -> dt.datetime:
    """A weekday local datetime ``days`` from today at ``hour:minute``."""
    day = timezone.localdate() + dt.timedelta(days=days)
    while day.weekday() >= 5:
        day += dt.timedelta(days=1)
    return timezone.make_aware(dt.datetime.combine(day, dt.time(hour, minute)))
