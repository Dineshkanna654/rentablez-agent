"""Normalize hardware serial numbers before diff comparison.

Windows WMI returns padded or casing-inconsistent serials (e.g. "4F2A8B   "),
which would cause false-positive SWAPPED reports if compared naively.
"""

import re

_HEX_RE = re.compile(r"^(0x)?[0-9a-fA-F]+$")


def normalize_serial(value):
    """Return a normalized form of *value* suitable for hardware-ID comparison.

    None passes through unchanged. Non-strings are coerced via str(). Whitespace
    is stripped and internal runs collapsed. Pure hex strings (with optional 0x
    prefix) are uppercased; all other strings keep their original case.
    """
    if value is None:
        return None

    if not isinstance(value, str):
        value = str(value)

    value = value.strip()
    value = re.sub(r"\s+", " ", value)

    if _HEX_RE.match(value):
        return value.upper()

    return value
