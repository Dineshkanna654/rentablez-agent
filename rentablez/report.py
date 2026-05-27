"""Build the JSON payload the backend expects for each check-in event.

Three status shapes (spec §7):
  baseline  — first registration; includes full fingerprint.
  ok        — nothing changed; fingerprint omitted to save bandwidth (spec §7.2).
  SWAPPED   — hardware change detected; includes full fingerprint and change list.
"""

from dataclasses import asdict

AGENT_VERSION = "1.0.0"

_VALID_STATUSES = {"baseline", "ok", "SWAPPED"}


def build_report(
    *,
    device_token: str,
    status: str,
    fingerprint: dict,
    os_info: dict,
    changes,
    collected_at: str,
) -> dict:
    """Return the report payload dict for the given check-in event."""
    if status not in _VALID_STATUSES:
        raise ValueError(f"Invalid status {status!r}; must be one of {_VALID_STATUSES}")

    if status == "SWAPPED" and not changes:
        raise ValueError("changes must be a non-empty list when status is 'SWAPPED'")

    report = {
        "device_token": device_token,
        "agent_version": AGENT_VERSION,
        "collected_at": collected_at,
        "status": status,
        "os": os_info,
    }

    if status == "baseline":
        report["fingerprint"] = fingerprint
    elif status == "SWAPPED":
        report["current_fingerprint"] = fingerprint
        report["changes"] = [asdict(c) for c in changes]

    return report
