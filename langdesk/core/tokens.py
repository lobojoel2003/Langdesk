"""Random, URL-safe tokens for calendar feeds and offer links."""

import secrets


def feed_token() -> str:
    return secrets.token_urlsafe(24)


def offer_token() -> str:
    return secrets.token_urlsafe(16)


def reply_code() -> str:
    """Four digits interpreters type back, e.g. ``YES 4821``."""
    return f"{secrets.randbelow(9000) + 1000}"
