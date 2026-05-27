"""Compare two hardware fingerprints; return Change records for strong-ID fields only.

Weak-ID fields (cycle_count, firmware, etc.) are not in the schema and are ignored.
"""

from dataclasses import dataclass
from typing import Any

from rentablez.normalize import normalize_serial

# Strong-ID schema (spec §6) — scalar components
SCALAR_SCHEMA: dict[str, list[str]] = {
    "machine":   ["serial_number", "hardware_uuid", "system_uuid"],
    "battery":   ["serial", "manufacturer", "device_name"],
    "bluetooth": ["address"],
}

# Strong-ID schema — list components matched by index
LIST_SCHEMA: dict[str, list[str]] = {
    "ram_modules": ["serial", "part_number", "manufacturer"],
    "storage":     ["serial", "model"],
    "displays":    ["edid_serial", "edid_vendor", "edid_product"],
    "gpus":        ["device_id", "vendor_id"],
    "network":     ["mac"],
}


@dataclass(frozen=True)
class Change:
    """Immutable record of a single strong-ID field discrepancy."""
    component: str
    field: str
    old: Any
    new: Any
    reason: str  # "value_changed" | "component_added" | "component_removed"


def _scalar_diff(component: str, field: str, old_val, new_val) -> list[Change]:
    """Return a Change if normalized values differ, else an empty list."""
    old_n, new_n = normalize_serial(old_val), normalize_serial(new_val)
    if old_n == new_n:
        return []
    reason = ("component_added" if old_n is None
              else "component_removed" if new_n is None
              else "value_changed")
    return [Change(component=component, field=field, old=old_val, new=new_val,
                   reason=reason)]


def diff_fingerprints(baseline: dict, current: dict) -> list[Change]:
    """Return a list of Change records for every strong-ID discrepancy."""
    changes: list[Change] = []

    for comp, fields in SCALAR_SCHEMA.items():
        base_comp = baseline.get(comp) or {}
        cur_comp = current.get(comp) or {}
        for field in fields:
            changes.extend(_scalar_diff(comp, field,
                                        base_comp.get(field), cur_comp.get(field)))

    for comp, fields in LIST_SCHEMA.items():
        base_list = baseline.get(comp) or []
        cur_list = current.get(comp) or []
        for i in range(max(len(base_list), len(cur_list))):
            label = f"{comp}[{i}]"
            if i >= len(base_list):
                changes.append(Change(component=label, field="*",
                                      old=None, new=cur_list[i],
                                      reason="component_added"))
            elif i >= len(cur_list):
                changes.append(Change(component=label, field="*",
                                      old=base_list[i], new=None,
                                      reason="component_removed"))
            else:
                for field in fields:
                    changes.extend(_scalar_diff(label, field,
                                                base_list[i].get(field),
                                                cur_list[i].get(field)))

    return changes
