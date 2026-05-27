"""HTTPS POST sender with transient/permanent outcome classification."""

import enum
import json
import urllib.request
from urllib.error import HTTPError, URLError

_TIMEOUT = 30
_TRANSIENT_CODES = {408, 429}


class SendOutcome(enum.Enum):
    SENT = "sent"
    TRANSIENT_FAILURE = "transient_failure"
    PERMANENT_FAILURE = "permanent_failure"


def send(endpoint: str, token: str, payload: dict) -> SendOutcome:
    """POST payload to endpoint; classify the outcome."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Rentablez-Agent/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            if 200 <= resp.status <= 299:
                return SendOutcome.SENT
            return SendOutcome.PERMANENT_FAILURE
    except HTTPError as exc:
        if exc.code >= 500 or exc.code in _TRANSIENT_CODES:
            return SendOutcome.TRANSIENT_FAILURE
        return SendOutcome.PERMANENT_FAILURE
    except (URLError, TimeoutError, OSError):
        return SendOutcome.TRANSIENT_FAILURE
