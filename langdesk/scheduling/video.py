"""Video fallback through Jitsi Meet.

Rooms get an unguessable random name and carry no client information. Point
``LANGDESK_JITSI_BASE_URL`` at a self-hosted Jitsi server to keep calls in-house.
"""

import secrets

from django.conf import settings


def new_video_link() -> str:
    room = f"{settings.LANGDESK_JITSI_ROOM_PREFIX}-{secrets.token_hex(10)}"
    return f"{settings.LANGDESK_JITSI_BASE_URL}/{room}"
