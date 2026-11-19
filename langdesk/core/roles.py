"""Two roles: requesters ask for interpreters, coordinators run the board.

Every signed-in user can request. Coordinators are superusers or members of the
``Coordinators`` group, which is created and given roster permissions on ``migrate``.
"""

from __future__ import annotations

from django.contrib.auth.decorators import user_passes_test

COORDINATORS = "Coordinators"
REQUESTERS = "Requesters"


def is_coordinator(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    cached = getattr(user, "_langdesk_is_coordinator", None)
    if cached is None:
        cached = user.groups.filter(name=COORDINATORS).exists()
        user._langdesk_is_coordinator = cached
    return cached


coordinator_required = user_passes_test(is_coordinator)
