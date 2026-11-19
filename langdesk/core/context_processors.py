from django.conf import settings

from langdesk.version import build_info

from .roles import is_coordinator


def langdesk(request) -> dict:
    return {
        "langdesk_build": build_info(),
        "org_name": settings.LANGDESK_ORG_NAME,
        "support_contact": settings.LANGDESK_SUPPORT_CONTACT,
        "is_coordinator": is_coordinator(getattr(request, "user", None)),
        "sms_simulator": settings.LANGDESK_SMS_SIMULATOR,
    }
