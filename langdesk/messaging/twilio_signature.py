"""Validate the ``X-Twilio-Signature`` header on inbound webhooks."""

import base64
import hashlib
import hmac


def compute(auth_token: str, url: str, params: dict[str, list[str]]) -> str:
    payload = url + "".join(f"{key}{value}" for key in sorted(params) for value in params[key])
    digest = hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def is_valid(auth_token: str, url: str, params: dict[str, list[str]], signature: str) -> bool:
    if not auth_token or not signature:
        return False
    return hmac.compare_digest(compute(auth_token, url, params), signature)
