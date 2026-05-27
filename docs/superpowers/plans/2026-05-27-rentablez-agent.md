# Rentablez Hardware Fingerprint Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python agent that runs once per boot on macOS and Windows rental laptops, captures a hardware fingerprint, compares it against a baseline saved on first boot, and reports the result (baseline / ok / SWAPPED) to the Rentablez backend — queueing locally when offline.

**Architecture:** Single Python script (`rentablez_agent.py`) that the OS service manager (launchd / Windows Service via nssm) invokes at boot. The script reads config, collects hardware via platform-specific subprocess calls, diffs against baseline, queues the report, drains the queue over HTTPS, then exits. State lives in JSON files on disk (`config.json`, `baseline.json`, `current.json`, `queue.json`). Two setup scripts (`setup_mac.sh`, `setup_windows.ps1`) handle one-shot installation.

**Tech Stack:**
- Python 3.10+ (stdlib only — no third-party packages, so no `pip install` step on target laptops). HTTP via `urllib.request`, JSON via `json`, subprocess via `subprocess`.
- Bash for the macOS setup/uninstall scripts.
- PowerShell 5+ for the Windows setup/uninstall scripts.
- `nssm` (Non-Sucking Service Manager) — bundled prebuilt binary — to register a one-shot Python script as a Windows Service.
- `launchd` plist for macOS service definition.
- `pytest` for unit/integration tests (dev-only; not installed on target laptops).

**Spec reference:** `docs/superpowers/specs/2026-05-26-rentablez-agent-design.md`

---

## File Structure

The agent script is split into focused modules. Each module has one responsibility and can be tested in isolation. They all live in a single Python *package* (`rentablez/`) for clean imports during testing — and the deployed `rentablez_agent.py` is a thin entrypoint that imports from the package. Package + entrypoint get copied together by the setup scripts.

```
rentablez-agent/
├── rentablez_agent.py              ← entrypoint invoked by launchd / nssm (~30 lines)
├── rentablez/
│   ├── __init__.py
│   ├── config.py                   ← load/validate config.json
│   ├── collectors/
│   │   ├── __init__.py             ← dispatcher: picks mac vs windows collector
│   │   ├── mac.py                  ← system_profiler-based collector
│   │   └── windows.py              ← PowerShell/WMI-based collector
│   ├── normalize.py                ← string normalization for serial comparison
│   ├── diff.py                     ← baseline-vs-current diff algorithm
│   ├── report.py                   ← builds the JSON payload (baseline/ok/SWAPPED)
│   ├── queue.py                    ← enqueue, drain, retention, atomic write
│   ├── sender.py                   ← HTTPS POST with retry/status classification
│   ├── paths.py                    ← per-OS paths for config, state, log files
│   ├── logger.py                   ← rotating file logger to agent.log
│   └── runner.py                   ← orchestrates one boot-time run (the "main" logic)
├── tests/
│   ├── __init__.py
│   ├── fixtures/
│   │   ├── mac_baseline.json
│   │   ├── windows_baseline.json
│   │   └── swap_examples.json
│   ├── test_normalize.py
│   ├── test_diff.py
│   ├── test_report.py
│   ├── test_queue.py
│   ├── test_sender.py
│   ├── test_config.py
│   ├── test_runner_integration.py
│   └── conftest.py
├── setup_mac.sh
├── setup_windows.ps1
├── uninstall_mac.sh
├── uninstall_windows.ps1
├── com.rentablez.agent.plist
├── vendor/
│   └── nssm.exe                    ← bundled binary, fetched once into the repo
├── README.md
└── pyproject.toml                  ← dev tooling only (pytest config)
```

**Why this split:** each module is small enough that the engineer can hold all of it in their head at once. `diff.py` doesn't know about subprocesses; `sender.py` doesn't know about JSON shapes; `runner.py` is the only place that knows about all the pieces.

**Why stdlib only:** target laptops are renter machines with no pre-installed third-party Python packages. Using only stdlib avoids any `pip install` step in the setup script, which would itself be a failure point.

---

## Task Order Rationale

Build bottom-up, leaving the OS-touching pieces (collectors, setup scripts) for last:

1. **Foundation** (paths, logger, normalize) — pure functions, no I/O, easy to TDD.
2. **State management** (config, queue) — file I/O on temp directories in tests.
3. **Comparison logic** (diff, report) — pure functions over JSON, easy to TDD.
4. **Network** (sender) — mocked in tests, no real network.
5. **Collectors** — platform-specific, hardest to test; build last so the rest is solid.
6. **Orchestration** (runner, entrypoint) — wires everything together.
7. **Setup scripts** — Bash/PowerShell, manually tested on real machines.
8. **Documentation** (README runbook).

---

## Pre-Task Setup

- [ ] **Step 0.1: Verify Python and pytest are installed for dev**

Run:
```bash
cd /home/dineshkanna/Desktop/rentablez-agent
python3 --version
python3 -m pip show pytest 2>/dev/null || python3 -m pip install --user pytest
```
Expected: Python 3.10 or higher; pytest available.

- [ ] **Step 0.2: Initialize Python package skeleton and pyproject.toml**

Create `pyproject.toml`:
```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "rentablez-agent"
version = "1.0.0"
description = "Rentablez hardware fingerprint agent"
requires-python = ">=3.10"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

Create empty files:
```bash
mkdir -p rentablez/collectors tests/fixtures vendor
touch rentablez/__init__.py rentablez/collectors/__init__.py
touch tests/__init__.py tests/conftest.py
```

- [ ] **Step 0.3: Verify pytest runs against the empty test directory**

Run: `python3 -m pytest tests/ -v`
Expected: `no tests ran in X.XXs` (no errors, just no tests).

- [ ] **Step 0.4: Commit scaffolding**

```bash
git add pyproject.toml rentablez/ tests/ vendor/
git commit -m "chore: scaffold python package and test layout"
```

---

## Task 1: Path resolution (`rentablez/paths.py`)

A single source of truth for where files live on each OS. Used everywhere else.

**Files:**
- Create: `rentablez/paths.py`
- Create: `tests/test_paths.py`

- [ ] **Step 1.1: Write the failing test**

Create `tests/test_paths.py`:
```python
import platform
from unittest.mock import patch
from rentablez import paths


def test_mac_paths():
    with patch("platform.system", return_value="Darwin"):
        p = paths.Paths.for_current_os()
        assert p.config_file == "/etc/rentablez/config.json"
        assert p.baseline_file == "/var/lib/rentablez/baseline.json"
        assert p.current_file == "/var/lib/rentablez/current.json"
        assert p.queue_file == "/var/lib/rentablez/queue.json"
        assert p.log_file == "/var/log/rentablez/agent.log"


def test_windows_paths():
    with patch("platform.system", return_value="Windows"):
        p = paths.Paths.for_current_os()
        assert p.config_file == r"C:\ProgramData\Rentablez\config.json"
        assert p.baseline_file == r"C:\ProgramData\Rentablez\baseline.json"
        assert p.current_file == r"C:\ProgramData\Rentablez\current.json"
        assert p.queue_file == r"C:\ProgramData\Rentablez\queue.json"
        assert p.log_file == r"C:\ProgramData\Rentablez\logs\agent.log"


def test_unsupported_os_raises():
    with patch("platform.system", return_value="Linux"):
        try:
            paths.Paths.for_current_os()
        except RuntimeError as e:
            assert "unsupported" in str(e).lower()
        else:
            raise AssertionError("expected RuntimeError")


def test_paths_override_root():
    p = paths.Paths(root="/tmp/test", os_name="Darwin")
    assert p.config_file == "/tmp/test/etc/rentablez/config.json"
    assert p.baseline_file == "/tmp/test/var/lib/rentablez/baseline.json"
```

- [ ] **Step 1.2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_paths.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'rentablez.paths'`.

- [ ] **Step 1.3: Implement `paths.py`**

Create `rentablez/paths.py`:
```python
"""Per-OS filesystem paths used by the agent.

Tests inject a `root` prefix; production uses the real OS paths.
"""
from __future__ import annotations

import platform
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath


@dataclass(frozen=True)
class Paths:
    config_file: str
    baseline_file: str
    current_file: str
    queue_file: str
    log_file: str
    log_dir: str
    state_dir: str

    @classmethod
    def for_current_os(cls) -> "Paths":
        return cls._for_os(platform.system(), root="")

    def __init__(self, root: str = "", os_name: str | None = None,
                 **explicit):
        if explicit:
            object.__setattr__(self, "__dict__", explicit)
            return
        resolved = type(self)._for_os(os_name or platform.system(), root)
        for k, v in resolved.__dict__.items():
            object.__setattr__(self, k, v)

    @classmethod
    def _for_os(cls, os_name: str, root: str) -> "Paths":
        if os_name == "Darwin":
            base_state = f"{root}/var/lib/rentablez"
            base_log = f"{root}/var/log/rentablez"
            return cls.__new__(cls)._populate(
                config_file=f"{root}/etc/rentablez/config.json",
                baseline_file=f"{base_state}/baseline.json",
                current_file=f"{base_state}/current.json",
                queue_file=f"{base_state}/queue.json",
                log_file=f"{base_log}/agent.log",
                log_dir=base_log,
                state_dir=base_state,
            )
        if os_name == "Windows":
            base = r"C:\ProgramData\Rentablez"
            return cls.__new__(cls)._populate(
                config_file=rf"{base}\config.json",
                baseline_file=rf"{base}\baseline.json",
                current_file=rf"{base}\current.json",
                queue_file=rf"{base}\queue.json",
                log_file=rf"{base}\logs\agent.log",
                log_dir=rf"{base}\logs",
                state_dir=base,
            )
        raise RuntimeError(f"unsupported OS: {os_name}")

    def _populate(self, **kw) -> "Paths":
        object.__setattr__(self, "__dict__", kw)
        return self
```

Note: the dataclass trick supports both `Paths.for_current_os()` and `Paths(root="/tmp", os_name="Darwin")` for tests. If this feels too clever, replace with two plain functions `mac_paths(root)` and `windows_paths(root)` plus a dispatcher.

- [ ] **Step 1.4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_paths.py -v`
Expected: 4 passed.

- [ ] **Step 1.5: Commit**

```bash
git add rentablez/paths.py tests/test_paths.py
git commit -m "feat(paths): per-OS path resolution with test override"
```

---

## Task 2: String normalization (`rentablez/normalize.py`)

Pure function. Trims whitespace, collapses internal runs, uppercases hex-looking strings. Used by the diff before comparing values.

**Files:**
- Create: `rentablez/normalize.py`
- Create: `tests/test_normalize.py`

- [ ] **Step 2.1: Write the failing test**

Create `tests/test_normalize.py`:
```python
from rentablez.normalize import normalize_serial


def test_strips_leading_and_trailing_whitespace():
    assert normalize_serial("  ABC123  ") == "ABC123"


def test_collapses_internal_whitespace():
    assert normalize_serial("ABC    123") == "ABC 123"


def test_uppercases_hex_looking_strings():
    assert normalize_serial("abcdef1234") == "ABCDEF1234"
    assert normalize_serial("0xdeadbeef") == "0XDEADBEEF"


def test_preserves_case_of_non_hex_strings():
    assert normalize_serial("Samsung_9C3D1E") == "Samsung_9C3D1E"


def test_handles_none():
    assert normalize_serial(None) is None


def test_handles_empty_string():
    assert normalize_serial("") == ""


def test_handles_non_string():
    assert normalize_serial(12345) == "12345"
    assert normalize_serial(True) == "True"


def test_idempotent():
    s = "  abc   def  "
    assert normalize_serial(normalize_serial(s)) == normalize_serial(s)
```

- [ ] **Step 2.2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_normalize.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'rentablez.normalize'`.

- [ ] **Step 2.3: Implement `normalize.py`**

Create `rentablez/normalize.py`:
```python
"""String normalization for hardware identifiers before comparison.

Hardware sources return values with varying whitespace and casing — Windows
WMI in particular pads serials and uses inconsistent case. Normalizing
prevents false-positive SWAPPED reports.
"""
from __future__ import annotations

import re

_HEX_ONLY = re.compile(r"^(0x)?[0-9a-fA-F]+$")
_WS_RUN = re.compile(r"\s+")


def normalize_serial(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    s = _WS_RUN.sub(" ", s)
    if _HEX_ONLY.match(s):
        return s.upper()
    return s
```

- [ ] **Step 2.4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_normalize.py -v`
Expected: 8 passed.

- [ ] **Step 2.5: Commit**

```bash
git add rentablez/normalize.py tests/test_normalize.py
git commit -m "feat(normalize): serial normalization for diff comparison"
```

---

## Task 3: Config loader (`rentablez/config.py`)

Reads `config.json`, validates required fields, returns a dataclass. Loud errors on missing/malformed file.

**Files:**
- Create: `rentablez/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 3.1: Write the failing test**

Create `tests/test_config.py`:
```python
import json
from pathlib import Path
import pytest
from rentablez.config import load_config, ConfigError


def test_loads_valid_config(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({
        "device_token": "RTBZ-LAP-00042",
        "endpoint": "https://api.example.com/devices/checkin",
        "installed_at": "2026-05-20T14:30:00Z",
    }))
    cfg = load_config(str(p))
    assert cfg.device_token == "RTBZ-LAP-00042"
    assert cfg.endpoint == "https://api.example.com/devices/checkin"
    assert cfg.installed_at == "2026-05-20T14:30:00Z"


def test_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(str(tmp_path / "nonexistent.json"))


def test_invalid_json_raises(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("not json at all {{{")
    with pytest.raises(ConfigError, match="invalid json"):
        load_config(str(p))


def test_missing_device_token_raises(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"endpoint": "https://x.com"}))
    with pytest.raises(ConfigError, match="device_token"):
        load_config(str(p))


def test_empty_device_token_raises(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"device_token": "", "endpoint": "https://x.com"}))
    with pytest.raises(ConfigError, match="device_token"):
        load_config(str(p))


def test_missing_endpoint_raises(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"device_token": "RTBZ-LAP-00042"}))
    with pytest.raises(ConfigError, match="endpoint"):
        load_config(str(p))


def test_installed_at_is_optional(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({
        "device_token": "RTBZ-LAP-00042",
        "endpoint": "https://x.com",
    }))
    cfg = load_config(str(p))
    assert cfg.installed_at is None
```

- [ ] **Step 3.2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'rentablez.config'`.

- [ ] **Step 3.3: Implement `config.py`**

Create `rentablez/config.py`:
```python
"""Loads and validates /etc/rentablez/config.json (or Windows equivalent).

The setup script writes this file; the agent only reads it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    device_token: str
    endpoint: str
    installed_at: str | None = None


def load_config(path: str) -> Config:
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"config file not found: {path}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"invalid json in {path}: {e}") from e

    token = data.get("device_token")
    if not isinstance(token, str) or not token.strip():
        raise ConfigError("device_token is required and must be a non-empty string")

    endpoint = data.get("endpoint")
    if not isinstance(endpoint, str) or not endpoint.strip():
        raise ConfigError("endpoint is required and must be a non-empty string")

    return Config(
        device_token=token.strip(),
        endpoint=endpoint.strip(),
        installed_at=data.get("installed_at"),
    )
```

- [ ] **Step 3.4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_config.py -v`
Expected: 7 passed.

- [ ] **Step 3.5: Commit**

```bash
git add rentablez/config.py tests/test_config.py
git commit -m "feat(config): load and validate config.json"
```

---

## Task 4: Diff algorithm (`rentablez/diff.py`)

The heart of the agent. Given baseline and current fingerprints, returns a list of `Change` records. Pure function, fully unit-testable.

**Files:**
- Create: `rentablez/diff.py`
- Create: `tests/test_diff.py`

- [ ] **Step 4.1: Write the failing tests**

Create `tests/test_diff.py`:
```python
from rentablez.diff import diff_fingerprints, Change


def _baseline():
    """Minimal valid baseline fingerprint."""
    return {
        "machine": {
            "serial_number": "C02XK1ABCD12",
            "hardware_uuid": "B8A7F2-AAAA-BBBB",
        },
        "ram_modules": [
            {"slot": "DIMM0", "serial": "SK_4F2A8B", "part_number": "HMA851",
             "manufacturer": "SK Hynix"},
        ],
        "storage": [
            {"name": "disk0", "serial": "Z1ABC123", "model": "APPLE SSD"},
        ],
        "battery": {
            "serial": "BAT-001", "manufacturer": "Sony", "device_name": "bq20z451",
        },
        "displays": [
            {"edid_serial": "DSPSRL1", "edid_vendor": "APP", "edid_product": "9CE8"},
        ],
        "gpus": [
            {"device_id": "0x1234", "vendor_id": "0x106B"},
        ],
        "network": [
            {"interface": "en0", "mac": "AA:BB:CC:DD:EE:FF"},
        ],
        "bluetooth": {"address": "11:22:33:44:55:66"},
    }


def test_no_changes_returns_empty_list():
    fp = _baseline()
    assert diff_fingerprints(fp, fp) == []


def test_machine_serial_change_detected():
    base = _baseline()
    cur = _baseline()
    cur["machine"]["serial_number"] = "DIFFERENT"
    changes = diff_fingerprints(base, cur)
    assert len(changes) == 1
    c = changes[0]
    assert c.component == "machine"
    assert c.field == "serial_number"
    assert c.old == "C02XK1ABCD12"
    assert c.new == "DIFFERENT"
    assert c.reason == "value_changed"


def test_ram_serial_change_detected():
    base = _baseline()
    cur = _baseline()
    cur["ram_modules"][0]["serial"] = "Samsung_9C3D1E"
    changes = diff_fingerprints(base, cur)
    assert any(c.component == "ram_modules[0]" and c.field == "serial"
               and c.old == "SK_4F2A8B" and c.new == "Samsung_9C3D1E"
               for c in changes)


def test_ram_module_removed():
    base = _baseline()
    cur = _baseline()
    cur["ram_modules"] = []
    changes = diff_fingerprints(base, cur)
    assert any(c.component == "ram_modules[0]" and c.reason == "component_removed"
               for c in changes)


def test_ram_module_added():
    base = _baseline()
    cur = _baseline()
    cur["ram_modules"].append({
        "slot": "DIMM1", "serial": "NEW", "part_number": "X", "manufacturer": "Y",
    })
    changes = diff_fingerprints(base, cur)
    assert any(c.component == "ram_modules[1]" and c.reason == "component_added"
               for c in changes)


def test_storage_replacement_detected():
    base = _baseline()
    cur = _baseline()
    cur["storage"][0]["serial"] = "Z9XYZ789"
    cur["storage"][0]["model"] = "Samsung 990 PRO"
    changes = diff_fingerprints(base, cur)
    assert len(changes) == 2
    fields = {c.field for c in changes}
    assert fields == {"serial", "model"}


def test_battery_swap_detected():
    base = _baseline()
    cur = _baseline()
    cur["battery"]["serial"] = "BAT-999"
    changes = diff_fingerprints(base, cur)
    assert len(changes) == 1
    assert changes[0].component == "battery"


def test_weak_id_field_ignored():
    """Cycle count, firmware version etc. should NOT trigger swap."""
    base = _baseline()
    base["battery"]["cycle_count"] = 50
    cur = _baseline()
    cur["battery"]["cycle_count"] = 350
    assert diff_fingerprints(base, cur) == []


def test_whitespace_difference_is_normalized():
    """Spec §6.3: leading/trailing whitespace should not trigger swap."""
    base = _baseline()
    cur = _baseline()
    cur["machine"]["serial_number"] = "  C02XK1ABCD12  "
    assert diff_fingerprints(base, cur) == []


def test_case_difference_in_hex_is_normalized():
    base = _baseline()
    base["bluetooth"]["address"] = "aa:bb:cc:dd:ee:ff"
    cur = _baseline()
    cur["bluetooth"]["address"] = "AA:BB:CC:DD:EE:FF"
    # MAC address with colons isn't pure hex per the regex, so this
    # specifically tests that the normalizer handles it.
    # Note: AA:BB:CC... is NOT purely hex due to colons, so case IS preserved.
    # We expect a change here unless we add MAC-specific normalization.
    # For v1 spec, leave as-is and verify it does flag.
    changes = diff_fingerprints(base, cur)
    assert len(changes) == 1  # documented behavior — MAC case sensitivity


def test_network_mac_change():
    base = _baseline()
    cur = _baseline()
    cur["network"][0]["mac"] = "11:22:33:44:55:66"
    changes = diff_fingerprints(base, cur)
    assert any(c.component == "network[0]" and c.field == "mac" for c in changes)


def test_display_swap():
    base = _baseline()
    cur = _baseline()
    cur["displays"][0]["edid_serial"] = "DSPSRL2"
    changes = diff_fingerprints(base, cur)
    assert any(c.field == "edid_serial" for c in changes)


def test_multiple_swaps_all_reported():
    base = _baseline()
    cur = _baseline()
    cur["ram_modules"][0]["serial"] = "X"
    cur["storage"][0]["serial"] = "Y"
    cur["battery"]["serial"] = "Z"
    changes = diff_fingerprints(base, cur)
    assert len(changes) == 3


def test_change_dataclass_has_expected_fields():
    c = Change(component="x", field="y", old="a", new="b", reason="value_changed")
    assert c.component == "x"
    assert c.field == "y"
    assert c.old == "a"
    assert c.new == "b"
    assert c.reason == "value_changed"
```

- [ ] **Step 4.2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_diff.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'rentablez.diff'`.

- [ ] **Step 4.3: Implement `diff.py`**

Create `rentablez/diff.py`:
```python
"""Compares baseline and current hardware fingerprints.

Only strong-ID fields (serials, MAC addresses, EDIDs, hardware UUIDs) are
compared. Weak-ID fields (cycle counts, firmware versions) are intentionally
ignored — they drift naturally over time.

See spec §6 for the field whitelist.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from rentablez.normalize import normalize_serial


@dataclass(frozen=True)
class Change:
    component: str
    field: str
    old: object
    new: object
    reason: str  # "value_changed" | "component_added" | "component_removed"


# Strong-ID schema: which fields under which components are compared.
_SCALAR_COMPONENTS: dict[str, tuple[str, ...]] = {
    "machine": ("serial_number", "hardware_uuid", "system_uuid"),
    "battery": ("serial", "manufacturer", "device_name"),
    "bluetooth": ("address",),
}

_LIST_COMPONENTS: dict[str, tuple[str, ...]] = {
    "ram_modules": ("serial", "part_number", "manufacturer"),
    "storage": ("serial", "model"),
    "displays": ("edid_serial", "edid_vendor", "edid_product"),
    "gpus": ("device_id", "vendor_id"),
    "network": ("mac",),
}


def diff_fingerprints(baseline: dict, current: dict) -> list[Change]:
    changes: list[Change] = []
    for component, fields in _SCALAR_COMPONENTS.items():
        changes.extend(_diff_scalar(component, fields,
                                    baseline.get(component) or {},
                                    current.get(component) or {}))
    for component, fields in _LIST_COMPONENTS.items():
        changes.extend(_diff_list(component, fields,
                                  baseline.get(component) or [],
                                  current.get(component) or []))
    return changes


def _diff_scalar(component: str, fields: Iterable[str],
                 base: dict, cur: dict) -> list[Change]:
    out: list[Change] = []
    for field in fields:
        b = normalize_serial(base.get(field))
        c = normalize_serial(cur.get(field))
        if b is None and c is None:
            continue
        if b is not None and c != b:
            out.append(Change(component, field, base.get(field), cur.get(field),
                              "value_changed" if c is not None else "component_removed"))
        elif b is None and c is not None:
            out.append(Change(component, field, None, cur.get(field),
                              "component_added"))
    return out


def _diff_list(component: str, fields: Iterable[str],
               base: list, cur: list) -> list[Change]:
    out: list[Change] = []
    max_len = max(len(base), len(cur))
    for i in range(max_len):
        path = f"{component}[{i}]"
        b_item = base[i] if i < len(base) else None
        c_item = cur[i] if i < len(cur) else None

        if b_item is None and c_item is not None:
            out.append(Change(path, "*", None, c_item, "component_added"))
            continue
        if b_item is not None and c_item is None:
            out.append(Change(path, "*", b_item, None, "component_removed"))
            continue

        for field in fields:
            b = normalize_serial(b_item.get(field))
            c = normalize_serial(c_item.get(field))
            if b is None and c is None:
                continue
            if b != c:
                reason = ("value_changed" if (b is not None and c is not None)
                          else "component_added" if b is None
                          else "component_removed")
                out.append(Change(path, field, b_item.get(field), c_item.get(field), reason))
    return out
```

- [ ] **Step 4.4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_diff.py -v`
Expected: 14 passed.

- [ ] **Step 4.5: Commit**

```bash
git add rentablez/diff.py tests/test_diff.py
git commit -m "feat(diff): baseline-vs-current fingerprint comparison"
```

---

## Task 5: Report builder (`rentablez/report.py`)

Turns a fingerprint (and optionally a diff result) into the JSON payload the backend expects. Three shapes: `baseline`, `ok`, `SWAPPED`.

**Files:**
- Create: `rentablez/report.py`
- Create: `tests/test_report.py`

- [ ] **Step 5.1: Write the failing test**

Create `tests/test_report.py`:
```python
from rentablez.diff import Change
from rentablez.report import build_report, AGENT_VERSION


def test_baseline_report_shape():
    fp = {"machine": {"serial_number": "S1"}}
    os_info = {"system": "Darwin", "release": "23.0"}
    r = build_report(
        device_token="RTBZ-LAP-00042",
        status="baseline",
        fingerprint=fp,
        os_info=os_info,
        changes=None,
        collected_at="2026-05-26T10:00:00Z",
    )
    assert r["device_token"] == "RTBZ-LAP-00042"
    assert r["agent_version"] == AGENT_VERSION
    assert r["collected_at"] == "2026-05-26T10:00:00Z"
    assert r["status"] == "baseline"
    assert r["fingerprint"] == fp
    assert r["os"] == os_info
    assert "changes" not in r
    assert "current_fingerprint" not in r


def test_ok_report_shape_omits_fingerprint():
    """spec §7.2: ok reports do NOT include full fingerprint."""
    fp = {"machine": {"serial_number": "S1"}}
    r = build_report(
        device_token="RTBZ-LAP-00042",
        status="ok",
        fingerprint=fp,
        os_info={"system": "Darwin"},
        changes=None,
        collected_at="2026-05-27T08:14:00Z",
    )
    assert r["status"] == "ok"
    assert "fingerprint" not in r
    assert "current_fingerprint" not in r
    assert "changes" not in r


def test_swapped_report_includes_changes_and_current_fingerprint():
    fp = {"machine": {"serial_number": "S2"}}
    changes = [
        Change("ram_modules[0]", "serial", "OLD", "NEW", "value_changed"),
    ]
    r = build_report(
        device_token="RTBZ-LAP-00042",
        status="SWAPPED",
        fingerprint=fp,
        os_info={"system": "Darwin"},
        changes=changes,
        collected_at="2026-05-27T08:14:00Z",
    )
    assert r["status"] == "SWAPPED"
    assert r["current_fingerprint"] == fp
    assert len(r["changes"]) == 1
    assert r["changes"][0] == {
        "component": "ram_modules[0]",
        "field": "serial",
        "old": "OLD",
        "new": "NEW",
        "reason": "value_changed",
    }


def test_invalid_status_raises():
    import pytest
    with pytest.raises(ValueError, match="status"):
        build_report(
            device_token="x",
            status="weird",
            fingerprint={},
            os_info={},
            changes=None,
            collected_at="2026-05-27T08:14:00Z",
        )


def test_swapped_requires_changes():
    import pytest
    with pytest.raises(ValueError, match="changes"):
        build_report(
            device_token="x",
            status="SWAPPED",
            fingerprint={},
            os_info={},
            changes=None,
            collected_at="2026-05-27T08:14:00Z",
        )
```

- [ ] **Step 5.2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_report.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 5.3: Implement `report.py`**

Create `rentablez/report.py`:
```python
"""Builds the JSON payload posted to the Rentablez backend.

Three shapes exist (see spec §7):
  - baseline: first-boot snapshot, includes full fingerprint
  - ok: clean boot, no fingerprint resent (backend already has baseline)
  - SWAPPED: includes changes[] and full current_fingerprint for forensics
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Optional

from rentablez.diff import Change


AGENT_VERSION = "1.0.0"
_VALID_STATUSES = {"baseline", "ok", "SWAPPED"}


def build_report(
    *,
    device_token: str,
    status: str,
    fingerprint: dict,
    os_info: dict,
    changes: Optional[list[Change]],
    collected_at: str,
) -> dict:
    if status not in _VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")
    if status == "SWAPPED" and not changes:
        raise ValueError("SWAPPED status requires non-empty changes")

    report: dict = {
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
    # "ok" → no extra fields

    return report
```

- [ ] **Step 5.4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_report.py -v`
Expected: 5 passed.

- [ ] **Step 5.5: Commit**

```bash
git add rentablez/report.py tests/test_report.py
git commit -m "feat(report): build baseline/ok/SWAPPED report payloads"
```

---

## Task 6: Queue (`rentablez/queue.py`)

Persistent JSON queue with atomic writes, retention policy, and corruption recovery.

**Files:**
- Create: `rentablez/queue.py`
- Create: `tests/test_queue.py`

- [ ] **Step 6.1: Write the failing test**

Create `tests/test_queue.py`:
```python
import json
import os
from pathlib import Path
import pytest
from rentablez.queue import Queue, QueueEntry


def test_enqueue_creates_entry(tmp_path):
    q = Queue(str(tmp_path / "queue.json"))
    q.enqueue({"status": "baseline", "device_token": "T"})
    entries = q.unsent()
    assert len(entries) == 1
    assert entries[0].payload == {"status": "baseline", "device_token": "T"}
    assert entries[0].sent is False
    assert entries[0].attempts == 0


def test_enqueue_persists_across_instances(tmp_path):
    path = str(tmp_path / "queue.json")
    q1 = Queue(path)
    q1.enqueue({"status": "ok"})
    q2 = Queue(path)
    assert len(q2.unsent()) == 1


def test_mark_sent(tmp_path):
    q = Queue(str(tmp_path / "queue.json"))
    q.enqueue({"status": "ok"})
    entry = q.unsent()[0]
    q.mark_sent(entry.id)
    assert q.unsent() == []


def test_increment_attempts(tmp_path):
    q = Queue(str(tmp_path / "queue.json"))
    q.enqueue({"status": "ok"})
    entry = q.unsent()[0]
    q.record_attempt(entry.id)
    refreshed = q.unsent()[0]
    assert refreshed.attempts == 1
    assert refreshed.last_attempt_at is not None


def test_corrupt_file_starts_fresh_and_archives(tmp_path):
    path = tmp_path / "queue.json"
    path.write_text("not json at all {{{")
    q = Queue(str(path))
    assert q.unsent() == []
    # original is renamed to queue.json.broken-<timestamp>
    broken = list(tmp_path.glob("queue.json.broken-*"))
    assert len(broken) == 1


def test_retention_evicts_newest_ok_when_full(tmp_path):
    """spec §9.3: drop NEWEST ok report when full; never drop baseline/SWAPPED."""
    q = Queue(str(tmp_path / "queue.json"), max_unsent=3)
    q.enqueue({"status": "baseline"})
    q.enqueue({"status": "ok"})  # this should be dropped when full
    q.enqueue({"status": "SWAPPED"})
    q.enqueue({"status": "ok"})  # triggers eviction
    statuses = [e.payload["status"] for e in q.unsent()]
    assert "baseline" in statuses
    assert "SWAPPED" in statuses
    # Three unsent total (cap of 3)
    assert len(q.unsent()) == 3


def test_retention_drops_new_ok_when_full_of_critical(tmp_path):
    """If queue is full and we'd otherwise drop a baseline/SWAPPED, drop the
    new ok instead."""
    q = Queue(str(tmp_path / "queue.json"), max_unsent=2)
    q.enqueue({"status": "baseline"})
    q.enqueue({"status": "SWAPPED"})
    q.enqueue({"status": "ok"})  # nothing droppable except itself
    statuses = [e.payload["status"] for e in q.unsent()]
    assert statuses == ["baseline", "SWAPPED"]


def test_sent_entries_pruned_after_retention_window(tmp_path):
    """spec §9.3: sent reports pruned 7 days after last_attempt_at."""
    import time
    from datetime import datetime, timezone, timedelta
    q = Queue(str(tmp_path / "queue.json"))
    q.enqueue({"status": "ok"})
    entry = q.unsent()[0]
    q.mark_sent(entry.id)
    # Force last_attempt_at to 8 days ago
    raw = json.loads(Path(tmp_path / "queue.json").read_text())
    raw[0]["last_attempt_at"] = (
        datetime.now(timezone.utc) - timedelta(days=8)
    ).isoformat()
    Path(tmp_path / "queue.json").write_text(json.dumps(raw))
    # Loading the queue should prune old sent entries
    q2 = Queue(str(tmp_path / "queue.json"))
    all_raw = json.loads(Path(tmp_path / "queue.json").read_text())
    assert all_raw == []


def test_atomic_write_uses_tempfile_then_rename(tmp_path, monkeypatch):
    """Verify the queue writes via a .tmp file then renames."""
    path = tmp_path / "queue.json"
    q = Queue(str(path))
    q.enqueue({"status": "ok"})
    # After enqueue completes, no .tmp file should remain
    assert not (tmp_path / "queue.json.tmp").exists()
    # The queue file should be readable JSON
    data = json.loads(path.read_text())
    assert len(data) == 1
```

- [ ] **Step 6.2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_queue.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 6.3: Implement `queue.py`**

Create `rentablez/queue.py`:
```python
"""Persistent JSON queue for outgoing reports.

The queue file is a list of entries. Writes are atomic (tmp file + rename).
Corrupt files are renamed aside and a fresh queue starts. Retention rules
protect baseline/SWAPPED reports from eviction (see spec §9.3).
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional


_CRITICAL_STATUSES = {"baseline", "SWAPPED"}
_SENT_RETENTION = timedelta(days=7)


@dataclass
class QueueEntry:
    id: str
    payload: dict
    attempts: int = 0
    last_attempt_at: Optional[str] = None
    sent: bool = False


class Queue:
    def __init__(self, path: str, max_unsent: int = 100):
        self.path = Path(path)
        self.max_unsent = max_unsent
        self._entries: list[QueueEntry] = self._load()
        self._prune_sent()
        self._save()

    def enqueue(self, payload: dict) -> None:
        entry = QueueEntry(
            id=f"rpt_{datetime.now(timezone.utc).isoformat()}_{len(self._entries)}",
            payload=payload,
        )
        if self._unsent_count() >= self.max_unsent:
            if not self._try_evict(payload):
                return  # drop the new entry; nothing droppable
        self._entries.append(entry)
        self._save()

    def unsent(self) -> list[QueueEntry]:
        return [e for e in self._entries if not e.sent]

    def mark_sent(self, entry_id: str) -> None:
        for e in self._entries:
            if e.id == entry_id:
                e.sent = True
                e.last_attempt_at = datetime.now(timezone.utc).isoformat()
                break
        self._save()

    def record_attempt(self, entry_id: str) -> None:
        for e in self._entries:
            if e.id == entry_id:
                e.attempts += 1
                e.last_attempt_at = datetime.now(timezone.utc).isoformat()
                break
        self._save()

    def _unsent_count(self) -> int:
        return sum(1 for e in self._entries if not e.sent)

    def _try_evict(self, new_payload: dict) -> bool:
        """Return True if room was made for new_payload, False if we should
        drop new_payload instead.

        Spec §9.3:
          - Drop NEWEST ok-status entry first.
          - Never drop baseline / SWAPPED.
          - If only critical entries fill the queue, drop the new one.
        """
        # Find newest ok-status entry (highest index, status=="ok", unsent)
        for i in range(len(self._entries) - 1, -1, -1):
            e = self._entries[i]
            if (not e.sent and
                e.payload.get("status") not in _CRITICAL_STATUSES):
                del self._entries[i]
                return True
        # If the new one is itself critical, evict the newest critical
        # (rare edge: queue full of baselines/SWAPPEDs from many resets).
        # Otherwise drop the incoming new entry.
        if new_payload.get("status") in _CRITICAL_STATUSES:
            for i in range(len(self._entries) - 1, -1, -1):
                e = self._entries[i]
                if not e.sent and e.payload.get("status") in _CRITICAL_STATUSES:
                    del self._entries[i]
                    return True
        return False

    def _prune_sent(self) -> None:
        now = datetime.now(timezone.utc)
        kept = []
        for e in self._entries:
            if e.sent and e.last_attempt_at:
                try:
                    when = datetime.fromisoformat(e.last_attempt_at)
                    if now - when > _SENT_RETENTION:
                        continue
                except ValueError:
                    pass
            kept.append(e)
        self._entries = kept

    def _load(self) -> list[QueueEntry]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return [QueueEntry(**row) for row in data]
        except (json.JSONDecodeError, TypeError, ValueError):
            # Corrupt file — archive it and start fresh.
            broken = self.path.with_name(
                f"{self.path.name}.broken-{int(time.time())}"
            )
            self.path.rename(broken)
            return []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(
            json.dumps([asdict(e) for e in self._entries], indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)
```

- [ ] **Step 6.4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_queue.py -v`
Expected: 9 passed.

- [ ] **Step 6.5: Commit**

```bash
git add rentablez/queue.py tests/test_queue.py
git commit -m "feat(queue): persistent JSON queue with retention rules"
```

---

## Task 7: Sender (`rentablez/sender.py`)

HTTPS POST with status classification. Tested with mocked HTTP.

**Files:**
- Create: `rentablez/sender.py`
- Create: `tests/test_sender.py`

- [ ] **Step 7.1: Write the failing test**

Create `tests/test_sender.py`:
```python
import json
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError, URLError
import pytest
from rentablez.sender import send, SendOutcome


def _mock_response(status: int, body: bytes = b"{}"):
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def test_2xx_returns_sent(mocker_or_none=None):
    with patch("urllib.request.urlopen", return_value=_mock_response(200)):
        outcome = send("https://api.example.com/checkin", "TOKEN", {"a": 1})
        assert outcome == SendOutcome.SENT


def test_201_returns_sent():
    with patch("urllib.request.urlopen", return_value=_mock_response(201)):
        outcome = send("https://api.example.com/checkin", "TOKEN", {"a": 1})
        assert outcome == SendOutcome.SENT


def test_400_returns_permanent_failure():
    err = HTTPError("https://x", 400, "Bad Request", {}, None)
    with patch("urllib.request.urlopen", side_effect=err):
        outcome = send("https://x", "T", {"a": 1})
        assert outcome == SendOutcome.PERMANENT_FAILURE


def test_401_returns_permanent_failure():
    err = HTTPError("https://x", 401, "Unauthorized", {}, None)
    with patch("urllib.request.urlopen", side_effect=err):
        outcome = send("https://x", "T", {"a": 1})
        assert outcome == SendOutcome.PERMANENT_FAILURE


def test_408_returns_transient():
    err = HTTPError("https://x", 408, "Request Timeout", {}, None)
    with patch("urllib.request.urlopen", side_effect=err):
        outcome = send("https://x", "T", {"a": 1})
        assert outcome == SendOutcome.TRANSIENT_FAILURE


def test_429_returns_transient():
    err = HTTPError("https://x", 429, "Too Many Requests", {}, None)
    with patch("urllib.request.urlopen", side_effect=err):
        outcome = send("https://x", "T", {"a": 1})
        assert outcome == SendOutcome.TRANSIENT_FAILURE


def test_500_returns_transient():
    err = HTTPError("https://x", 500, "Server Error", {}, None)
    with patch("urllib.request.urlopen", side_effect=err):
        outcome = send("https://x", "T", {"a": 1})
        assert outcome == SendOutcome.TRANSIENT_FAILURE


def test_network_error_returns_transient():
    with patch("urllib.request.urlopen", side_effect=URLError("no route")):
        outcome = send("https://x", "T", {"a": 1})
        assert outcome == SendOutcome.TRANSIENT_FAILURE


def test_includes_authorization_header():
    captured = {}

    def fake_urlopen(req, *args, **kwargs):
        captured["headers"] = dict(req.header_items())
        captured["data"] = req.data
        return _mock_response(200)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        send("https://api.example.com", "MYTOKEN", {"status": "ok"})

    assert captured["headers"]["Authorization"] == "Bearer MYTOKEN"
    assert captured["headers"]["Content-type"] == "application/json"
    assert json.loads(captured["data"]) == {"status": "ok"}


def test_timeout_propagated_to_urlopen():
    captured = {}

    def fake_urlopen(req, *args, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        return _mock_response(200)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        send("https://x", "T", {})

    assert captured["timeout"] == 30
```

- [ ] **Step 7.2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_sender.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 7.3: Implement `sender.py`**

Create `rentablez/sender.py`:
```python
"""HTTPS POST to the Rentablez backend.

Classifies the result as SENT, TRANSIENT_FAILURE (retry next boot), or
PERMANENT_FAILURE (mark sent so we stop retrying a broken report).
"""
from __future__ import annotations

import enum
import json
import urllib.request
from urllib.error import HTTPError, URLError


_TIMEOUT_SECONDS = 30
_TRANSIENT_HTTP_CODES = {408, 429}


class SendOutcome(enum.Enum):
    SENT = "sent"
    TRANSIENT_FAILURE = "transient_failure"
    PERMANENT_FAILURE = "permanent_failure"


def send(endpoint: str, token: str, payload: dict) -> SendOutcome:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Rentablez-Agent/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            if 200 <= resp.status < 300:
                return SendOutcome.SENT
            return SendOutcome.PERMANENT_FAILURE
    except HTTPError as e:
        if e.code >= 500 or e.code in _TRANSIENT_HTTP_CODES:
            return SendOutcome.TRANSIENT_FAILURE
        return SendOutcome.PERMANENT_FAILURE
    except (URLError, TimeoutError, OSError):
        return SendOutcome.TRANSIENT_FAILURE
```

- [ ] **Step 7.4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_sender.py -v`
Expected: 10 passed.

- [ ] **Step 7.5: Commit**

```bash
git add rentablez/sender.py tests/test_sender.py
git commit -m "feat(sender): HTTPS POST with transient/permanent classification"
```

---

## Task 8: Logger (`rentablez/logger.py`)

Rotating file logger. Thin wrapper around stdlib `logging`.

**Files:**
- Create: `rentablez/logger.py`
- Create: `tests/test_logger.py`

- [ ] **Step 8.1: Write the failing test**

Create `tests/test_logger.py`:
```python
import logging
from rentablez.logger import setup_logger


def test_logger_writes_to_file(tmp_path):
    log_file = tmp_path / "agent.log"
    logger = setup_logger(str(log_file), level=logging.INFO)
    logger.info("hello world")
    # Force flush
    for h in logger.handlers:
        h.flush()
    content = log_file.read_text()
    assert "hello world" in content


def test_logger_includes_timestamp(tmp_path):
    log_file = tmp_path / "agent.log"
    logger = setup_logger(str(log_file))
    logger.info("test")
    for h in logger.handlers:
        h.flush()
    line = log_file.read_text()
    # ISO timestamp at the start
    assert line[0:4].isdigit()  # year


def test_logger_creates_directory(tmp_path):
    log_file = tmp_path / "nested" / "dir" / "agent.log"
    setup_logger(str(log_file))
    assert log_file.parent.is_dir()


def test_logger_includes_level(tmp_path):
    log_file = tmp_path / "agent.log"
    logger = setup_logger(str(log_file))
    logger.error("oh no")
    for h in logger.handlers:
        h.flush()
    assert "ERROR" in log_file.read_text()
```

- [ ] **Step 8.2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_logger.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 8.3: Implement `logger.py`**

Create `rentablez/logger.py`:
```python
"""Rotating file logger for the agent."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


_LOGGER_NAME = "rentablez"
_MAX_BYTES = 10 * 1024 * 1024
_BACKUP_COUNT = 5


def setup_logger(log_file: str, level: int = logging.INFO) -> logging.Logger:
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(level)
    # Remove pre-existing handlers (important for tests / repeated calls).
    logger.handlers.clear()

    handler = RotatingFileHandler(
        log_file, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    ))
    logger.addHandler(handler)
    return logger
```

- [ ] **Step 8.4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_logger.py -v`
Expected: 4 passed.

- [ ] **Step 8.5: Commit**

```bash
git add rentablez/logger.py tests/test_logger.py
git commit -m "feat(logger): rotating file logger"
```

---

## Task 9: macOS collector (`rentablez/collectors/mac.py`)

Refactors the existing collector code into a single function `collect() -> dict` that runs `system_profiler` and returns the structured fingerprint. Tested by injecting a fake subprocess runner.

**Files:**
- Create: `rentablez/collectors/mac.py`
- Create: `tests/test_collector_mac.py`
- Create: `tests/fixtures/mac_system_profiler_hw.json` (sample output)

- [ ] **Step 9.1: Create a fixture file with realistic system_profiler output**

Create `tests/fixtures/mac_system_profiler_hw.json`:
```json
{
  "SPHardwareDataType": [
    {
      "machine_model": "MacBookPro18,3",
      "machine_name": "MacBook Pro",
      "chip_type": "Apple M1 Pro",
      "number_processors": "8",
      "physical_memory": "16 GB",
      "serial_number": "C02XK1ABCD12",
      "platform_UUID": "B8A7F2AA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"
    }
  ]
}
```

Create `tests/fixtures/mac_system_profiler_nvme.json`:
```json
{
  "SPNVMeDataType": [
    {
      "_items": [
        {
          "_name": "APPLE SSD AP0512R",
          "device_model": "APPLE SSD AP0512R",
          "device_serial": "0ABCDEF12345",
          "device_revision": "846.100.",
          "size": "500.28 GB"
        }
      ]
    }
  ]
}
```

(Create minimal stub fixtures for the other data types as needed by the tests; below we'll dependency-inject the runner so we only need fixtures for what we test.)

- [ ] **Step 9.2: Write the failing test**

Create `tests/test_collector_mac.py`:
```python
import json
from pathlib import Path
import pytest
from rentablez.collectors.mac import collect


FIXTURES = Path(__file__).parent / "fixtures"


def _fake_runner(responses: dict):
    """Build a runner that returns the right JSON for each data type."""
    def runner(args):
        # args is the system_profiler command list
        for dt, payload in responses.items():
            if dt in args:
                return json.dumps(payload)
        return "{}"
    return runner


def test_machine_fields_extracted():
    hw = json.loads((FIXTURES / "mac_system_profiler_hw.json").read_text())
    runner = _fake_runner({"SPHardwareDataType": hw})
    fp = collect(runner=runner)
    assert fp["machine"]["serial_number"] == "C02XK1ABCD12"
    assert fp["machine"]["hardware_uuid"] == "B8A7F2AA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"
    assert fp["machine"]["model_name"] == "MacBook Pro"


def test_storage_extracted():
    nvme = json.loads((FIXTURES / "mac_system_profiler_nvme.json").read_text())
    runner = _fake_runner({"SPNVMeDataType": nvme})
    fp = collect(runner=runner)
    assert len(fp["storage"]) >= 1
    disk = fp["storage"][0]
    assert disk["serial"] == "0ABCDEF12345"
    assert disk["model"] == "APPLE SSD AP0512R"


def test_missing_data_type_yields_empty_section():
    runner = _fake_runner({})  # returns "{}" for everything
    fp = collect(runner=runner)
    assert fp["machine"] == {}
    assert fp["storage"] == []
    assert fp["ram_modules"] == []


def test_subprocess_error_does_not_crash():
    def bad_runner(args):
        raise OSError("system_profiler not found")
    fp = collect(runner=bad_runner)
    # Should return a fingerprint with empty sections, not raise
    assert isinstance(fp, dict)
    assert "machine" in fp
```

- [ ] **Step 9.3: Run test to verify it fails**

Run: `python3 -m pytest tests/test_collector_mac.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 9.4: Implement `mac.py`**

Create `rentablez/collectors/mac.py`:
```python
"""macOS hardware fingerprint collector.

Wraps `system_profiler -json <DataType>` calls. The `runner` parameter is
injectable for testing — production passes the default subprocess runner.
"""
from __future__ import annotations

import json
import subprocess
from typing import Callable


def _default_runner(args: list[str]) -> str:
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=30, check=False,
        )
        return result.stdout or "{}"
    except (subprocess.SubprocessError, OSError):
        return "{}"


def _profile(runner: Callable[[list[str]], str], data_type: str) -> dict:
    out = runner(["system_profiler", data_type, "-json"])
    try:
        return json.loads(out)
    except (json.JSONDecodeError, TypeError):
        return {}


def collect(runner: Callable[[list[str]], str] | None = None) -> dict:
    if runner is None:
        runner = _default_runner

    def safe_call(fn):
        try:
            return fn()
        except Exception:
            return None

    hw = safe_call(lambda: _profile(runner, "SPHardwareDataType")
                   .get("SPHardwareDataType", [{}])[0]) or {}
    machine = {
        "serial_number": hw.get("serial_number"),
        "hardware_uuid": hw.get("platform_UUID"),
        "model_name": hw.get("machine_name"),
        "model_identifier": hw.get("machine_model"),
        "chip": hw.get("chip_type") or hw.get("cpu_type"),
    }

    ram_modules = _collect_ram(runner)
    storage = _collect_storage(runner)
    battery = _collect_battery(runner)
    displays, gpus = _collect_displays_and_gpus(runner)
    network = _collect_network(runner)
    bluetooth = _collect_bluetooth(runner)

    return {
        "machine": machine,
        "ram_modules": ram_modules,
        "storage": storage,
        "battery": battery,
        "displays": displays,
        "gpus": gpus,
        "network": network,
        "bluetooth": bluetooth,
    }


def _collect_ram(runner) -> list[dict]:
    data = _profile(runner, "SPMemoryDataType").get("SPMemoryDataType", [])
    modules = []
    for m in data:
        items = m.get("_items") or [m]
        for slot in items:
            modules.append({
                "slot": slot.get("_name"),
                "size": slot.get("dimm_size"),
                "type": slot.get("dimm_type"),
                "speed": slot.get("dimm_speed"),
                "manufacturer": slot.get("dimm_manufacturer"),
                "part_number": slot.get("dimm_part_number"),
                "serial": slot.get("dimm_serial_number"),
            })
    return modules


def _collect_storage(runner) -> list[dict]:
    out = []
    for dt in ("SPNVMeDataType", "SPSerialATADataType"):
        data = _profile(runner, dt).get(dt, [])
        for controller in data:
            for dev in controller.get("_items", []) or []:
                out.append({
                    "name": dev.get("_name"),
                    "model": dev.get("device_model") or dev.get("_name"),
                    "serial": dev.get("device_serial"),
                    "revision": dev.get("device_revision"),
                    "size": dev.get("size"),
                })
    return out


def _collect_battery(runner) -> dict:
    pwr = _profile(runner, "SPPowerDataType").get("SPPowerDataType", [])
    bat = {}
    for entry in pwr:
        info = entry.get("sppower_battery_model_info") or {}
        if info:
            bat.update({
                "manufacturer": info.get("sppower_battery_manufacturer"),
                "device_name": info.get("sppower_battery_device_name"),
                "serial": info.get("sppower_battery_serial_number"),
                "firmware": info.get("sppower_battery_firmware_version"),
            })
        health = entry.get("sppower_battery_health_info") or {}
        if health:
            bat["cycle_count"] = health.get("sppower_battery_cycle_count")
            bat["condition"] = health.get("sppower_battery_health")
    return bat


def _collect_displays_and_gpus(runner):
    data = _profile(runner, "SPDisplaysDataType").get("SPDisplaysDataType", [])
    displays = []
    gpus = []
    for gpu in data:
        gpus.append({
            "model": gpu.get("sppci_model") or gpu.get("_name"),
            "vendor": gpu.get("spdisplays_vendor"),
            "device_id": gpu.get("spdisplays_device-id"),
            "vendor_id": gpu.get("spdisplays_vendor-id"),
            "vram": gpu.get("spdisplays_vram") or gpu.get("spdisplays_vram_shared"),
        })
        for screen in gpu.get("spdisplays_ndrvs", []) or []:
            displays.append({
                "name": screen.get("_name"),
                "edid_vendor": screen.get("_spdisplays_display-vendor-id"),
                "edid_product": screen.get("_spdisplays_display-product-id"),
                "edid_serial": screen.get("_spdisplays_display-serial-number"),
            })
    return displays, gpus


def _collect_network(runner) -> list[dict]:
    net = _profile(runner, "SPNetworkDataType").get("SPNetworkDataType", [])
    out = []
    for iface in net:
        eth = iface.get("Ethernet")
        mac = eth.get("MAC Address") if isinstance(eth, dict) else None
        out.append({
            "name": iface.get("_name"),
            "interface": iface.get("interface"),
            "type": iface.get("type"),
            "hardware": iface.get("hardware"),
            "mac": mac,
        })
    return out


def _collect_bluetooth(runner) -> dict:
    bt = _profile(runner, "SPBluetoothDataType").get("SPBluetoothDataType", [])
    if not bt:
        return {}
    ctrl = bt[0].get("controller_properties") or {}
    return {
        "address": ctrl.get("controller_address"),
        "chipset": ctrl.get("controller_chipset"),
        "firmware": ctrl.get("controller_firmwareVersion"),
    }
```

- [ ] **Step 9.5: Run test to verify it passes**

Run: `python3 -m pytest tests/test_collector_mac.py -v`
Expected: 4 passed.

- [ ] **Step 9.6: Commit**

```bash
git add rentablez/collectors/mac.py tests/test_collector_mac.py tests/fixtures/
git commit -m "feat(collector): macOS fingerprint collector via system_profiler"
```

---

## Task 10: Windows collector (`rentablez/collectors/windows.py`)

Same shape as the macOS collector, but uses PowerShell + CIM/WMI. Same injectable-runner pattern.

**Files:**
- Create: `rentablez/collectors/windows.py`
- Create: `tests/test_collector_windows.py`
- Create: `tests/fixtures/windows_*.json`

- [ ] **Step 10.1: Create fixture files**

Create `tests/fixtures/windows_machine.json`:
```json
{
  "Name": "MacBook Pro",
  "Vendor": "Apple Inc.",
  "Version": "MacBookPro18,3",
  "IdentifyingNumber": "C02XK1ABCD12",
  "UUID": "B8A7F2AA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"
}
```

Create `tests/fixtures/windows_ram.json`:
```json
[
  {
    "BankLabel": "BANK 0",
    "DeviceLocator": "DIMM0",
    "Manufacturer": "SK Hynix",
    "PartNumber": "HMA851S6JJR6N-VK   ",
    "SerialNumber": "4F2A8B   ",
    "Capacity": 8589934592,
    "Speed": 3200,
    "MemoryType": 26,
    "FormFactor": 12
  }
]
```

Note the trailing whitespace in `PartNumber` and `SerialNumber` — this is realistic and the diff's normalizer will handle it.

- [ ] **Step 10.2: Write the failing test**

Create `tests/test_collector_windows.py`:
```python
import json
from pathlib import Path
from rentablez.collectors.windows import collect


FIXTURES = Path(__file__).parent / "fixtures"


def _fake_runner(responses: dict[str, str]):
    """Match by substring in the powershell script body."""
    def runner(script: str) -> str:
        for marker, payload in responses.items():
            if marker in script:
                return payload
        return "[]"
    return runner


def test_machine_fields_extracted():
    machine_json = (FIXTURES / "windows_machine.json").read_text()
    runner = _fake_runner({"Win32_ComputerSystemProduct": machine_json})
    fp = collect(runner=runner)
    assert fp["machine"]["system_serial"] == "C02XK1ABCD12"
    assert fp["machine"]["system_uuid"] == "B8A7F2AA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"
    assert fp["machine"]["vendor"] == "Apple Inc."


def test_ram_modules_extracted_with_whitespace():
    ram_json = (FIXTURES / "windows_ram.json").read_text()
    runner = _fake_runner({"Win32_PhysicalMemory": ram_json})
    fp = collect(runner=runner)
    assert len(fp["ram_modules"]) == 1
    m = fp["ram_modules"][0]
    # Note: the collector preserves the raw value; the normalizer is what
    # trims it during diff. We document the raw value here.
    assert m["serial"] == "4F2A8B   "
    assert m["part_number"] == "HMA851S6JJR6N-VK   "
    assert m["slot"] == "DIMM0"


def test_missing_data_yields_empty_sections():
    runner = _fake_runner({})
    fp = collect(runner=runner)
    assert fp["machine"] == {}
    assert fp["ram_modules"] == []
    assert fp["storage"] == []


def test_subprocess_error_handled_gracefully():
    def bad(script):
        raise OSError("powershell missing")
    fp = collect(runner=bad)
    assert isinstance(fp, dict)
```

- [ ] **Step 10.3: Run test to verify it fails**

Run: `python3 -m pytest tests/test_collector_windows.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 10.4: Implement `windows.py`**

Create `rentablez/collectors/windows.py`:
```python
"""Windows hardware fingerprint collector via PowerShell + WMI/CIM."""
from __future__ import annotations

import json
import subprocess
from typing import Callable


def _default_runner(script: str) -> str:
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=30, check=False,
        )
        return result.stdout or ""
    except (subprocess.SubprocessError, OSError):
        return ""


def _query(runner: Callable[[str], str], script: str):
    out = runner(script)
    if not out or not out.strip():
        return None
    try:
        return json.loads(out)
    except (json.JSONDecodeError, TypeError):
        return None


def _as_list(x):
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]


def collect(runner: Callable[[str], str] | None = None) -> dict:
    if runner is None:
        runner = _default_runner

    return {
        "machine": _collect_machine(runner),
        "ram_modules": _collect_ram(runner),
        "storage": _collect_storage(runner),
        "battery": _collect_battery(runner),
        "displays": _collect_displays(runner),
        "gpus": _collect_gpus(runner),
        "network": _collect_network(runner),
        "bluetooth": _collect_bluetooth(runner),
    }


def _collect_machine(runner) -> dict:
    data = _query(runner,
        "Get-CimInstance Win32_ComputerSystemProduct | "
        "Select-Object Name,Vendor,Version,IdentifyingNumber,UUID | "
        "ConvertTo-Json"
    )
    if not data:
        return {}
    return {
        "vendor": data.get("Vendor"),
        "model": data.get("Name") or data.get("Version"),
        "system_serial": data.get("IdentifyingNumber"),
        "system_uuid": data.get("UUID"),
    }


def _collect_ram(runner) -> list[dict]:
    data = _as_list(_query(runner,
        "Get-CimInstance Win32_PhysicalMemory | "
        "Select-Object BankLabel,DeviceLocator,Manufacturer,PartNumber,"
        "SerialNumber,Capacity,Speed,MemoryType,FormFactor | ConvertTo-Json"
    ))
    return [{
        "bank": m.get("BankLabel"),
        "slot": m.get("DeviceLocator"),
        "manufacturer": m.get("Manufacturer"),
        "part_number": m.get("PartNumber"),
        "serial": m.get("SerialNumber"),
        "capacity": m.get("Capacity"),
        "speed": m.get("Speed"),
    } for m in data]


def _collect_storage(runner) -> list[dict]:
    data = _as_list(_query(runner,
        "Get-PhysicalDisk | "
        "Select-Object DeviceId,FriendlyName,Manufacturer,Model,SerialNumber,"
        "MediaType,BusType,Size,FirmwareVersion | ConvertTo-Json"
    ))
    return [{
        "name": d.get("FriendlyName"),
        "manufacturer": d.get("Manufacturer"),
        "model": d.get("Model"),
        "serial": d.get("SerialNumber"),
        "media_type": d.get("MediaType"),
        "bus_type": d.get("BusType"),
        "size": d.get("Size"),
        "firmware": d.get("FirmwareVersion"),
    } for d in data]


def _collect_battery(runner) -> dict:
    basic = _query(runner,
        "Get-CimInstance Win32_Battery | "
        "Select-Object Name,DeviceID,DesignCapacity,FullChargeCapacity,"
        "Chemistry | ConvertTo-Json"
    ) or {}
    static = _query(runner,
        "Get-CimInstance -Namespace root\\WMI -ClassName BatteryStaticData "
        "-ErrorAction SilentlyContinue | "
        "Select-Object DeviceName,ManufactureName,SerialNumber,UniqueID,"
        "DesignedCapacity | ConvertTo-Json"
    ) or {}
    cycles = _query(runner,
        "Get-CimInstance -Namespace root\\WMI -ClassName BatteryCycleCount "
        "-ErrorAction SilentlyContinue | Select-Object CycleCount | ConvertTo-Json"
    ) or {}
    return {
        "name": basic.get("Name"),
        "chemistry": basic.get("Chemistry"),
        "design_capacity": static.get("DesignedCapacity") or basic.get("DesignCapacity"),
        "full_charge_capacity": basic.get("FullChargeCapacity"),
        "manufacturer": static.get("ManufactureName"),
        "device_name": static.get("DeviceName"),
        "serial": static.get("SerialNumber"),
        "cycle_count": cycles.get("CycleCount"),
    }


def _collect_displays(runner) -> list[dict]:
    return _as_list(_query(runner,
        "Get-CimInstance -Namespace root\\WMI -ClassName WmiMonitorID "
        "-ErrorAction SilentlyContinue | ForEach-Object { "
        "[PSCustomObject]@{"
        "  Manufacturer = -join ($_.ManufacturerName | Where-Object {$_ -ne 0} | "
        "                       ForEach-Object {[char]$_});"
        "  ProductCode  = -join ($_.ProductCodeID  | Where-Object {$_ -ne 0} | "
        "                       ForEach-Object {[char]$_});"
        "  Serial       = -join ($_.SerialNumberID | Where-Object {$_ -ne 0} | "
        "                       ForEach-Object {[char]$_});"
        "} } | ConvertTo-Json"
    ))


def _collect_gpus(runner) -> list[dict]:
    data = _as_list(_query(runner,
        "Get-CimInstance Win32_VideoController | "
        "Select-Object Name,AdapterCompatibility,VideoProcessor,DriverVersion,"
        "PNPDeviceID,AdapterRAM | ConvertTo-Json"
    ))
    return [{
        "name": g.get("Name"),
        "vendor": g.get("AdapterCompatibility"),
        "processor": g.get("VideoProcessor"),
        "driver": g.get("DriverVersion"),
        "device_id": g.get("PNPDeviceID"),
        "vram": g.get("AdapterRAM"),
    } for g in data]


def _collect_network(runner) -> list[dict]:
    return _as_list(_query(runner,
        "Get-NetAdapter -Physical -ErrorAction SilentlyContinue | "
        "Select-Object Name,InterfaceDescription,MacAddress,Status,LinkSpeed | "
        "ConvertTo-Json"
    ))


def _collect_bluetooth(runner) -> dict:
    data = _as_list(_query(runner,
        "Get-PnpDevice -Class Bluetooth -PresentOnly -ErrorAction SilentlyContinue | "
        "Select-Object FriendlyName,Manufacturer,DeviceID | "
        "ConvertTo-Json"
    ))
    if not data:
        return {}
    first = data[0]
    return {
        "address": first.get("DeviceID"),
        "name": first.get("FriendlyName"),
        "manufacturer": first.get("Manufacturer"),
    }
```

Note: the Windows network/display sections preserve PowerShell's field names (e.g. `MacAddress`) because the diff's `_LIST_COMPONENTS` for `network` uses `"mac"` — we need a rename. Fix it:

```python
def _collect_network(runner) -> list[dict]:
    raw = _as_list(_query(runner,
        "Get-NetAdapter -Physical -ErrorAction SilentlyContinue | "
        "Select-Object Name,InterfaceDescription,MacAddress,Status,LinkSpeed | "
        "ConvertTo-Json"
    ))
    return [{
        "name": n.get("Name"),
        "description": n.get("InterfaceDescription"),
        "mac": n.get("MacAddress"),
        "status": n.get("Status"),
        "speed": n.get("LinkSpeed"),
    } for n in raw]


def _collect_displays(runner) -> list[dict]:
    raw = _as_list(_query(runner,
        "Get-CimInstance -Namespace root\\WMI -ClassName WmiMonitorID "
        "-ErrorAction SilentlyContinue | ForEach-Object { "
        "[PSCustomObject]@{"
        "  Manufacturer = -join ($_.ManufacturerName | Where-Object {$_ -ne 0} | "
        "                       ForEach-Object {[char]$_});"
        "  ProductCode  = -join ($_.ProductCodeID  | Where-Object {$_ -ne 0} | "
        "                       ForEach-Object {[char]$_});"
        "  Serial       = -join ($_.SerialNumberID | Where-Object {$_ -ne 0} | "
        "                       ForEach-Object {[char]$_});"
        "} } | ConvertTo-Json"
    ))
    return [{
        "edid_vendor": d.get("Manufacturer"),
        "edid_product": d.get("ProductCode"),
        "edid_serial": d.get("Serial"),
    } for d in raw]
```

Replace the earlier definitions in `windows.py` with these two renamed versions so the keys line up with the diff schema.

- [ ] **Step 10.5: Run test to verify it passes**

Run: `python3 -m pytest tests/test_collector_windows.py -v`
Expected: 4 passed.

- [ ] **Step 10.6: Commit**

```bash
git add rentablez/collectors/windows.py tests/test_collector_windows.py tests/fixtures/windows_*.json
git commit -m "feat(collector): Windows fingerprint collector via PowerShell"
```

---

## Task 11: Collector dispatcher (`rentablez/collectors/__init__.py`)

One-line dispatcher: picks the right collector for the current OS.

**Files:**
- Modify: `rentablez/collectors/__init__.py`
- Create: `tests/test_collector_dispatch.py`

- [ ] **Step 11.1: Write the failing test**

Create `tests/test_collector_dispatch.py`:
```python
from unittest.mock import patch
import pytest
from rentablez.collectors import collect_for_current_os


def test_picks_mac_on_darwin():
    with patch("platform.system", return_value="Darwin"):
        with patch("rentablez.collectors.mac.collect", return_value={"x": "mac"}):
            assert collect_for_current_os()["x"] == "mac"


def test_picks_windows_on_windows():
    with patch("platform.system", return_value="Windows"):
        with patch("rentablez.collectors.windows.collect",
                   return_value={"x": "win"}):
            assert collect_for_current_os()["x"] == "win"


def test_raises_on_unsupported():
    with patch("platform.system", return_value="Linux"):
        with pytest.raises(RuntimeError, match="unsupported"):
            collect_for_current_os()
```

- [ ] **Step 11.2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_collector_dispatch.py -v`
Expected: FAIL.

- [ ] **Step 11.3: Implement the dispatcher**

Edit `rentablez/collectors/__init__.py`:
```python
"""Dispatcher that picks the right hardware collector for the current OS."""
from __future__ import annotations

import platform


def collect_for_current_os() -> dict:
    system = platform.system()
    if system == "Darwin":
        from rentablez.collectors import mac
        return mac.collect()
    if system == "Windows":
        from rentablez.collectors import windows
        return windows.collect()
    raise RuntimeError(f"unsupported OS: {system}")
```

- [ ] **Step 11.4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_collector_dispatch.py -v`
Expected: 3 passed.

- [ ] **Step 11.5: Commit**

```bash
git add rentablez/collectors/__init__.py tests/test_collector_dispatch.py
git commit -m "feat(collector): dispatcher selects collector by OS"
```

---

## Task 12: Runner (`rentablez/runner.py`) — orchestrates the full boot-time flow

This is the brain of one agent run. Pure orchestration; all I/O components are passed in for testability.

**Files:**
- Create: `rentablez/runner.py`
- Create: `tests/test_runner_integration.py`

- [ ] **Step 12.1: Write the failing test**

Create `tests/test_runner_integration.py`:
```python
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from rentablez.config import Config
from rentablez.runner import run_once
from rentablez.sender import SendOutcome


def _cfg():
    return Config(
        device_token="RTBZ-LAP-00042",
        endpoint="https://api.example.com/checkin",
    )


def _baseline_fp():
    return {
        "machine": {"serial_number": "S1", "hardware_uuid": "U1"},
        "ram_modules": [{"slot": "DIMM0", "serial": "RAM1",
                         "part_number": "PN", "manufacturer": "MFG"}],
        "storage": [{"name": "d0", "serial": "ST1", "model": "M"}],
        "battery": {"serial": "B1", "manufacturer": "Sony", "device_name": "bq"},
        "displays": [],
        "gpus": [],
        "network": [],
        "bluetooth": {},
    }


def test_first_boot_writes_baseline_and_queues_report(tmp_path):
    fp = _baseline_fp()

    def collector():
        return fp

    sent_payloads = []
    def sender(endpoint, token, payload):
        sent_payloads.append(payload)
        return SendOutcome.SENT

    run_once(
        cfg=_cfg(),
        paths_root=str(tmp_path),
        os_name="Darwin",
        collector=collector,
        sender=sender,
        os_info={"system": "Darwin"},
        now_iso="2026-05-26T10:00:00Z",
    )

    # baseline file was written
    baseline_path = tmp_path / "var/lib/rentablez/baseline.json"
    assert baseline_path.exists()
    saved = json.loads(baseline_path.read_text())
    assert saved == fp

    # the baseline report was sent
    assert len(sent_payloads) == 1
    assert sent_payloads[0]["status"] == "baseline"
    assert sent_payloads[0]["fingerprint"] == fp


def test_second_boot_no_swap_sends_ok(tmp_path):
    fp = _baseline_fp()
    sent_payloads = []

    def sender(endpoint, token, payload):
        sent_payloads.append(payload)
        return SendOutcome.SENT

    # First boot establishes the baseline.
    run_once(
        cfg=_cfg(), paths_root=str(tmp_path), os_name="Darwin",
        collector=lambda: fp, sender=sender,
        os_info={"system": "Darwin"}, now_iso="2026-05-26T10:00:00Z",
    )
    sent_payloads.clear()

    # Second boot, same hardware.
    run_once(
        cfg=_cfg(), paths_root=str(tmp_path), os_name="Darwin",
        collector=lambda: fp, sender=sender,
        os_info={"system": "Darwin"}, now_iso="2026-05-27T08:00:00Z",
    )

    assert len(sent_payloads) == 1
    assert sent_payloads[0]["status"] == "ok"
    assert "fingerprint" not in sent_payloads[0]


def test_second_boot_with_swap_sends_swapped(tmp_path):
    base_fp = _baseline_fp()
    new_fp = _baseline_fp()
    new_fp["ram_modules"][0]["serial"] = "RAM_DIFFERENT"

    sent_payloads = []
    def sender(endpoint, token, payload):
        sent_payloads.append(payload)
        return SendOutcome.SENT

    # First boot: original fingerprint.
    run_once(
        cfg=_cfg(), paths_root=str(tmp_path), os_name="Darwin",
        collector=lambda: base_fp, sender=sender,
        os_info={"system": "Darwin"}, now_iso="2026-05-26T10:00:00Z",
    )
    sent_payloads.clear()

    # Second boot: RAM swapped.
    run_once(
        cfg=_cfg(), paths_root=str(tmp_path), os_name="Darwin",
        collector=lambda: new_fp, sender=sender,
        os_info={"system": "Darwin"}, now_iso="2026-05-27T08:00:00Z",
    )

    assert len(sent_payloads) == 1
    r = sent_payloads[0]
    assert r["status"] == "SWAPPED"
    assert r["current_fingerprint"] == new_fp
    assert any(c["component"] == "ram_modules[0]" and c["field"] == "serial"
               for c in r["changes"])


def test_offline_keeps_report_in_queue(tmp_path):
    fp = _baseline_fp()

    def sender(endpoint, token, payload):
        return SendOutcome.TRANSIENT_FAILURE

    run_once(
        cfg=_cfg(), paths_root=str(tmp_path), os_name="Darwin",
        collector=lambda: fp, sender=sender,
        os_info={"system": "Darwin"}, now_iso="2026-05-26T10:00:00Z",
    )

    queue = json.loads((tmp_path / "var/lib/rentablez/queue.json").read_text())
    assert len(queue) == 1
    assert queue[0]["sent"] is False
    assert queue[0]["attempts"] == 1


def test_queue_drained_on_reconnect(tmp_path):
    fp = _baseline_fp()
    online = False
    sent_payloads = []

    def sender(endpoint, token, payload):
        if not online:
            return SendOutcome.TRANSIENT_FAILURE
        sent_payloads.append(payload)
        return SendOutcome.SENT

    # Boot 1 — offline
    run_once(
        cfg=_cfg(), paths_root=str(tmp_path), os_name="Darwin",
        collector=lambda: fp, sender=sender,
        os_info={"system": "Darwin"}, now_iso="2026-05-26T10:00:00Z",
    )
    # Boot 2 — still offline
    run_once(
        cfg=_cfg(), paths_root=str(tmp_path), os_name="Darwin",
        collector=lambda: fp, sender=sender,
        os_info={"system": "Darwin"}, now_iso="2026-05-27T10:00:00Z",
    )
    # Boot 3 — online, drain
    online = True
    run_once(
        cfg=_cfg(), paths_root=str(tmp_path), os_name="Darwin",
        collector=lambda: fp, sender=sender,
        os_info={"system": "Darwin"}, now_iso="2026-05-28T10:00:00Z",
    )

    # 3 reports should now have been sent (baseline + 2 oks).
    assert len(sent_payloads) == 3
    statuses = [p["status"] for p in sent_payloads]
    assert statuses == ["baseline", "ok", "ok"]


def test_baseline_file_corrupted_treated_as_missing(tmp_path):
    baseline = tmp_path / "var/lib/rentablez/baseline.json"
    baseline.parent.mkdir(parents=True)
    baseline.write_text("not json at all {{{")

    fp = _baseline_fp()
    sent = []
    def sender(endpoint, token, payload):
        sent.append(payload)
        return SendOutcome.SENT

    run_once(
        cfg=_cfg(), paths_root=str(tmp_path), os_name="Darwin",
        collector=lambda: fp, sender=sender,
        os_info={"system": "Darwin"}, now_iso="2026-05-27T10:00:00Z",
    )

    assert sent[0]["status"] == "baseline"
    # Baseline file should now be valid JSON containing the current fp
    saved = json.loads(baseline.read_text())
    assert saved == fp


def test_current_json_always_written(tmp_path):
    fp = _baseline_fp()
    run_once(
        cfg=_cfg(), paths_root=str(tmp_path), os_name="Darwin",
        collector=lambda: fp, sender=lambda *a: SendOutcome.SENT,
        os_info={"system": "Darwin"}, now_iso="2026-05-26T10:00:00Z",
    )
    current = json.loads((tmp_path / "var/lib/rentablez/current.json").read_text())
    assert current == fp
```

- [ ] **Step 12.2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_runner_integration.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 12.3: Implement `runner.py`**

Create `rentablez/runner.py`:
```python
"""One boot-time agent run.

Designed for testability: every external dependency (collector, sender,
filesystem root) is injectable. The production entrypoint wires in real
implementations.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from rentablez.config import Config
from rentablez.diff import diff_fingerprints
from rentablez.paths import Paths
from rentablez.queue import Queue
from rentablez.report import build_report
from rentablez.sender import SendOutcome


_log = logging.getLogger("rentablez")


def run_once(
    *,
    cfg: Config,
    paths_root: str,
    os_name: str,
    collector: Callable[[], dict],
    sender: Callable[[str, str, dict], SendOutcome],
    os_info: dict,
    now_iso: str | None = None,
) -> None:
    paths = Paths(root=paths_root, os_name=os_name)
    Path(paths.state_dir).mkdir(parents=True, exist_ok=True)

    timestamp = now_iso or datetime.now(timezone.utc).isoformat()

    # 1. Collect current fingerprint.
    try:
        current = collector()
    except Exception as e:
        _log.exception("collector failed: %s", e)
        return

    # 2. Write current.json (for local debugging).
    _atomic_write_json(paths.current_file, current)

    # 3. Load baseline (or create one if missing/corrupt).
    baseline = _load_baseline(paths.baseline_file)

    # 4. Build the report.
    if baseline is None:
        _atomic_write_json(paths.baseline_file, current)
        report = build_report(
            device_token=cfg.device_token, status="baseline",
            fingerprint=current, os_info=os_info, changes=None,
            collected_at=timestamp,
        )
    else:
        changes = diff_fingerprints(baseline, current)
        if changes:
            report = build_report(
                device_token=cfg.device_token, status="SWAPPED",
                fingerprint=current, os_info=os_info, changes=changes,
                collected_at=timestamp,
            )
        else:
            report = build_report(
                device_token=cfg.device_token, status="ok",
                fingerprint=current, os_info=os_info, changes=None,
                collected_at=timestamp,
            )

    # 5. Enqueue the new report.
    queue = Queue(paths.queue_file)
    queue.enqueue(report)

    # 6. Drain unsent reports in order.
    for entry in queue.unsent():
        outcome = sender(cfg.endpoint, cfg.device_token, entry.payload)
        if outcome == SendOutcome.SENT:
            queue.mark_sent(entry.id)
        elif outcome == SendOutcome.PERMANENT_FAILURE:
            _log.error("permanent send failure for %s — marking sent",
                       entry.id)
            queue.mark_sent(entry.id)
        else:
            queue.record_attempt(entry.id)
            # Stop draining on first transient failure — preserve order
            # and avoid hammering a backend that's clearly unhappy.
            break


def _load_baseline(path: str) -> dict | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        _log.warning("baseline file corrupt at %s — recreating", path)
        return None


def _atomic_write_json(path: str, data: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    import os
    os.replace(tmp, p)
```

- [ ] **Step 12.4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_runner_integration.py -v`
Expected: 7 passed.

- [ ] **Step 12.5: Run the full test suite**

Run: `python3 -m pytest -v`
Expected: all tests pass across all modules.

- [ ] **Step 12.6: Commit**

```bash
git add rentablez/runner.py tests/test_runner_integration.py
git commit -m "feat(runner): orchestrate boot-time run end-to-end"
```

---

## Task 13: Entrypoint script (`rentablez_agent.py`)

The deployed script. Tiny — just wires up real dependencies and calls `run_once`.

**Files:**
- Create: `rentablez_agent.py` (repo root)

- [ ] **Step 13.1: Write `rentablez_agent.py`**

Create `rentablez_agent.py`:
```python
#!/usr/bin/env python3
"""Rentablez agent entrypoint.

Invoked at boot by launchd (macOS) or by nssm (Windows). Reads config,
collects hardware, compares against baseline, queues + sends the report,
exits.
"""
from __future__ import annotations

import logging
import platform
import sys
from datetime import datetime, timezone

from rentablez.collectors import collect_for_current_os
from rentablez.config import load_config, ConfigError
from rentablez.logger import setup_logger
from rentablez.paths import Paths
from rentablez.runner import run_once
from rentablez.sender import send


def _os_info() -> dict:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "hostname": platform.node(),
    }


def main() -> int:
    paths = Paths.for_current_os()
    logger = setup_logger(paths.log_file)

    try:
        cfg = load_config(paths.config_file)
    except ConfigError as e:
        logger.error("config load failed: %s", e)
        return 1

    logger.info("agent starting (token=%s)", cfg.device_token)

    try:
        run_once(
            cfg=cfg,
            paths_root="",
            os_name=platform.system(),
            collector=collect_for_current_os,
            sender=send,
            os_info=_os_info(),
            now_iso=datetime.now(timezone.utc).isoformat(),
        )
    except Exception:
        logger.exception("agent run failed")
        return 1

    logger.info("agent run complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 13.2: Smoke-test the entrypoint imports cleanly**

Run: `python3 -c "import rentablez_agent"`
Expected: no output, exit 0 (just verifies imports resolve).

- [ ] **Step 13.3: Commit**

```bash
git add rentablez_agent.py
git commit -m "feat: top-level rentablez_agent.py entrypoint"
```

---

## Task 14: LaunchDaemon plist template

**Files:**
- Create: `com.rentablez.agent.plist`

- [ ] **Step 14.1: Write the plist**

Create `com.rentablez.agent.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.rentablez.agent</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/usr/local/rentablez/rentablez_agent.py</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <false/>
  <key>StandardOutPath</key>
  <string>/var/log/rentablez/agent.log</string>
  <key>StandardErrorPath</key>
  <string>/var/log/rentablez/agent.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONPATH</key>
    <string>/usr/local/rentablez</string>
  </dict>
</dict>
</plist>
```

`PYTHONPATH` lets `rentablez_agent.py` import the `rentablez` package from the same directory.

- [ ] **Step 14.2: Validate the plist syntax**

Run: `python3 -c "import plistlib; plistlib.loads(open('com.rentablez.agent.plist','rb').read())"`
Expected: no output (parse success).

- [ ] **Step 14.3: Commit**

```bash
git add com.rentablez.agent.plist
git commit -m "feat: LaunchDaemon plist for one-shot boot run"
```

---

## Task 15: Setup script for macOS (`setup_mac.sh`)

**Files:**
- Create: `setup_mac.sh`

- [ ] **Step 15.1: Write the script**

Create `setup_mac.sh`:
```bash
#!/usr/bin/env bash
# setup_mac.sh — one-shot installer for the Rentablez agent on macOS.
# Run as: sudo ./setup_mac.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: must run as root (try: sudo $0)" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found. macOS should ship with python3 at /usr/bin/python3." >&2
  exit 1
fi

# Resolve script directory so we can copy local files.
SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Prompt for device token, with format validation.
TOKEN=""
while [[ ! "$TOKEN" =~ ^RTBZ-LAP-[0-9]{5,}$ ]]; do
  read -rp "Enter device token (e.g. RTBZ-LAP-00042): " TOKEN
  if [[ ! "$TOKEN" =~ ^RTBZ-LAP-[0-9]{5,}$ ]]; then
    echo "  Invalid format. Must look like RTBZ-LAP-<5+ digits>."
  fi
done

ENDPOINT="${RENTABLEZ_ENDPOINT:-https://api.rentablez.com/devices/checkin}"

echo "==> Creating directories"
mkdir -p /usr/local/rentablez /etc/rentablez /var/lib/rentablez /var/log/rentablez
chown -R root:wheel /etc/rentablez /var/lib/rentablez /var/log/rentablez
chmod 700 /etc/rentablez /var/lib/rentablez

echo "==> Copying agent files"
cp -R "$SCRIPT_DIR/rentablez" /usr/local/rentablez/
cp "$SCRIPT_DIR/rentablez_agent.py" /usr/local/rentablez/
chown -R root:wheel /usr/local/rentablez
chmod 755 /usr/local/rentablez /usr/local/rentablez/rentablez_agent.py
find /usr/local/rentablez/rentablez -type f -exec chmod 644 {} \;
find /usr/local/rentablez/rentablez -type d -exec chmod 755 {} \;

echo "==> Writing config"
cat > /etc/rentablez/config.json <<JSON
{
  "device_token": "$TOKEN",
  "endpoint": "$ENDPOINT",
  "installed_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
JSON
chmod 600 /etc/rentablez/config.json
chown root:wheel /etc/rentablez/config.json

echo "==> Installing LaunchDaemon"
cp "$SCRIPT_DIR/com.rentablez.agent.plist" /Library/LaunchDaemons/
chown root:wheel /Library/LaunchDaemons/com.rentablez.agent.plist
chmod 644 /Library/LaunchDaemons/com.rentablez.agent.plist

# Bootstrap (idempotent: bootout first if already loaded)
launchctl bootout system /Library/LaunchDaemons/com.rentablez.agent.plist 2>/dev/null || true
launchctl bootstrap system /Library/LaunchDaemons/com.rentablez.agent.plist
launchctl kickstart system/com.rentablez.agent

echo
echo "===================================="
echo "  Rentablez agent installed."
echo "  Device token: $TOKEN"
echo "  Endpoint:     $ENDPOINT"
echo "  Log file:     /var/log/rentablez/agent.log"
echo "===================================="
```

- [ ] **Step 15.2: Make it executable and shellcheck it**

Run:
```bash
chmod +x setup_mac.sh
command -v shellcheck >/dev/null && shellcheck setup_mac.sh || echo "shellcheck not installed, skipping"
```
Expected: no errors. If shellcheck is unavailable on the dev machine, install with `apt install shellcheck` (Linux) or `brew install shellcheck` (Mac).

- [ ] **Step 15.3: Commit**

```bash
git add setup_mac.sh
git commit -m "feat: setup_mac.sh installs agent as a LaunchDaemon"
```

---

## Task 16: Uninstall script for macOS (`uninstall_mac.sh`)

**Files:**
- Create: `uninstall_mac.sh`

- [ ] **Step 16.1: Write the script**

Create `uninstall_mac.sh`:
```bash
#!/usr/bin/env bash
# uninstall_mac.sh — remove the Rentablez agent but preserve baseline.json
# so reinstalling on the same laptop keeps its original baseline.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: must run as root (try: sudo $0)" >&2
  exit 1
fi

echo "==> Stopping LaunchDaemon"
launchctl bootout system /Library/LaunchDaemons/com.rentablez.agent.plist 2>/dev/null || true

echo "==> Removing files (preserving baseline.json)"
rm -f /Library/LaunchDaemons/com.rentablez.agent.plist
rm -rf /usr/local/rentablez
rm -rf /etc/rentablez
# Keep /var/lib/rentablez/baseline.json; clear the rest of state dir.
find /var/lib/rentablez -mindepth 1 ! -name baseline.json -delete 2>/dev/null || true

echo "==> Uninstall complete."
echo "    Baseline preserved at /var/lib/rentablez/baseline.json"
echo "    To fully wipe, run: sudo rm -rf /var/lib/rentablez /var/log/rentablez"
```

- [ ] **Step 16.2: Make it executable and shellcheck it**

Run:
```bash
chmod +x uninstall_mac.sh
command -v shellcheck >/dev/null && shellcheck uninstall_mac.sh || true
```
Expected: clean.

- [ ] **Step 16.3: Commit**

```bash
git add uninstall_mac.sh
git commit -m "feat: uninstall_mac.sh preserves baseline for reinstall"
```

---

## Task 17: Setup script for Windows (`setup_windows.ps1`)

**Files:**
- Create: `setup_windows.ps1`
- Add to repo: `vendor/nssm.exe` (downloaded once from https://nssm.cc/release/nssm-2.24.zip — bundle the 64-bit binary)

- [ ] **Step 17.1: Document how to obtain `vendor/nssm.exe`**

Create `vendor/README.md`:
```markdown
# Vendored binaries

## nssm.exe

Source: https://nssm.cc/release/nssm-2.24.zip

To refresh:
1. Download the zip from the URL above.
2. Extract `nssm-2.24/win64/nssm.exe`.
3. Place it at `vendor/nssm.exe` in this repo.
4. Verify SHA-256 against the official release notes.

This binary is bundled because target Windows laptops will not have it
pre-installed and we don't want the setup script to download from the
internet (the laptop may be offline at setup time).
```

(The engineer running the plan downloads nssm.exe manually before testing on Windows; the script assumes it's present in `vendor/`.)

- [ ] **Step 17.2: Write the PowerShell setup script**

Create `setup_windows.ps1`:
```powershell
# setup_windows.ps1 — one-shot installer for the Rentablez agent on Windows.
# Run as Administrator from an elevated PowerShell prompt.
#requires -RunAsAdministrator
$ErrorActionPreference = "Stop"

# Resolve script directory.
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Verify Python 3.10+ is installed; if not, install via winget.
function Test-Python {
    try {
        $version = (& python --version 2>&1) -replace 'Python ', ''
        $parts = $version.Split('.')
        return ([int]$parts[0] -ge 3 -and [int]$parts[1] -ge 10)
    } catch {
        return $false
    }
}

if (-not (Test-Python)) {
    Write-Host "==> Python 3.10+ not found; installing via winget."
    winget install -e --id Python.Python.3.12 --silent --accept-source-agreements --accept-package-agreements
    # Refresh PATH for current session.
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path","User")
    if (-not (Test-Python)) {
        Write-Error "Python install failed. Aborting."
        exit 1
    }
}

# Resolve python.exe path.
$PythonPath = (Get-Command python).Source

# Prompt for device token with format validation.
$Token = ""
while ($Token -notmatch '^RTBZ-LAP-\d{5,}$') {
    $Token = Read-Host "Enter device token (e.g. RTBZ-LAP-00042)"
    if ($Token -notmatch '^RTBZ-LAP-\d{5,}$') {
        Write-Host "  Invalid format. Must look like RTBZ-LAP-<5+ digits>."
    }
}

$Endpoint = if ($env:RENTABLEZ_ENDPOINT) { $env:RENTABLEZ_ENDPOINT } else { "https://api.rentablez.com/devices/checkin" }

Write-Host "==> Creating directories"
New-Item -ItemType Directory -Force -Path "C:\Rentablez" | Out-Null
New-Item -ItemType Directory -Force -Path "C:\ProgramData\Rentablez" | Out-Null
New-Item -ItemType Directory -Force -Path "C:\ProgramData\Rentablez\logs" | Out-Null

# Lock down C:\ProgramData\Rentablez ACLs: only SYSTEM and Administrators.
$acl = Get-Acl "C:\ProgramData\Rentablez"
$acl.SetAccessRuleProtection($true, $false)
$acl.Access | ForEach-Object { $acl.RemoveAccessRule($_) | Out-Null }
$acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
    "NT AUTHORITY\SYSTEM", "FullControl", "ContainerInherit,ObjectInherit", "None", "Allow")))
$acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
    "BUILTIN\Administrators", "FullControl", "ContainerInherit,ObjectInherit", "None", "Allow")))
Set-Acl "C:\ProgramData\Rentablez" $acl

Write-Host "==> Copying agent files"
Copy-Item -Recurse -Force "$ScriptDir\rentablez" "C:\Rentablez\"
Copy-Item -Force "$ScriptDir\rentablez_agent.py" "C:\Rentablez\"
Copy-Item -Force "$ScriptDir\vendor\nssm.exe" "C:\Rentablez\"

Write-Host "==> Writing config"
$cfg = @{
    device_token = $Token
    endpoint = $Endpoint
    installed_at = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
}
$cfg | ConvertTo-Json | Set-Content -Path "C:\ProgramData\Rentablez\config.json" -Encoding UTF8

Write-Host "==> Registering service via nssm"
$nssm = "C:\Rentablez\nssm.exe"
# Remove existing service if present (idempotency).
& $nssm stop RentablezAgent 2>$null
& $nssm remove RentablezAgent confirm 2>$null

& $nssm install RentablezAgent $PythonPath "C:\Rentablez\rentablez_agent.py"
& $nssm set RentablezAgent Start SERVICE_AUTO_START
& $nssm set RentablezAgent ObjectName LocalSystem
& $nssm set RentablezAgent DisplayName "Rentablez Hardware Monitor"
& $nssm set RentablezAgent Description "Reports hardware fingerprint at boot to detect part swaps."
& $nssm set RentablezAgent AppDirectory "C:\Rentablez"
& $nssm set RentablezAgent AppEnvironmentExtra "PYTHONPATH=C:\Rentablez"
& $nssm set RentablezAgent AppExit Default Exit
& $nssm set RentablezAgent AppStdout "C:\ProgramData\Rentablez\logs\nssm-stdout.log"
& $nssm set RentablezAgent AppStderr "C:\ProgramData\Rentablez\logs\nssm-stderr.log"

Write-Host "==> Starting service (first run captures baseline)"
& $nssm start RentablezAgent

Write-Host ""
Write-Host "===================================="
Write-Host "  Rentablez agent installed."
Write-Host "  Device token: $Token"
Write-Host "  Endpoint:     $Endpoint"
Write-Host "  Log file:     C:\ProgramData\Rentablez\logs\agent.log"
Write-Host "===================================="
```

- [ ] **Step 17.3: Commit**

```bash
git add setup_windows.ps1 vendor/README.md
git commit -m "feat: setup_windows.ps1 registers service via nssm"
```

---

## Task 18: Uninstall script for Windows (`uninstall_windows.ps1`)

**Files:**
- Create: `uninstall_windows.ps1`

- [ ] **Step 18.1: Write the script**

Create `uninstall_windows.ps1`:
```powershell
# uninstall_windows.ps1 — removes the Rentablez agent but preserves
# baseline.json so reinstalling on the same laptop keeps its original
# baseline.
#requires -RunAsAdministrator
$ErrorActionPreference = "Continue"

$nssm = "C:\Rentablez\nssm.exe"

Write-Host "==> Stopping service"
if (Test-Path $nssm) {
    & $nssm stop RentablezAgent 2>$null
    & $nssm remove RentablezAgent confirm 2>$null
} else {
    # Fallback if nssm.exe already removed
    Stop-Service -Name RentablezAgent -Force -ErrorAction SilentlyContinue
    sc.exe delete RentablezAgent 2>$null
}

Write-Host "==> Removing files (preserving baseline.json)"
Remove-Item -Recurse -Force "C:\Rentablez" -ErrorAction SilentlyContinue
# Preserve baseline.json; remove the rest of the state dir.
Get-ChildItem "C:\ProgramData\Rentablez" -Recurse -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -ne "baseline.json" } |
    Remove-Item -Force -Recurse -ErrorAction SilentlyContinue

Write-Host "==> Uninstall complete."
Write-Host "    Baseline preserved at C:\ProgramData\Rentablez\baseline.json"
Write-Host "    To fully wipe, run: Remove-Item -Recurse -Force C:\ProgramData\Rentablez"
```

- [ ] **Step 18.2: Commit**

```bash
git add uninstall_windows.ps1
git commit -m "feat: uninstall_windows.ps1 preserves baseline"
```

---

## Task 19: README runbook

**Files:**
- Create: `README.md`

- [ ] **Step 19.1: Write the runbook**

Create `README.md`:
```markdown
# Rentablez Hardware Fingerprint Agent

Boots-time hardware fingerprint collector. Detects part swaps on rental
laptops by comparing each boot against a baseline captured at warehouse
setup.

## What you need

- A laptop that is in its final shipped configuration (correct RAM, SSD,
  battery, etc.).
- The device token assigned to this laptop (format: `RTBZ-LAP-<5+ digits>`).
- Administrator/root access to the laptop.
- An internet connection (helpful but not required — offline reports queue
  locally and send on next boot).

## macOS install

```bash
sudo ./setup_mac.sh
```

You'll be prompted for the device token. The script will:
1. Copy the agent into `/usr/local/rentablez/`.
2. Write `/etc/rentablez/config.json` with the token.
3. Register the LaunchDaemon and start it immediately, which captures the
   baseline.

Verify with:
```bash
launchctl list | grep com.rentablez.agent
cat /var/lib/rentablez/baseline.json | python3 -m json.tool | head
tail /var/log/rentablez/agent.log
```

## Windows install

Open PowerShell as Administrator, then:
```powershell
cd path\to\rentablez-agent
.\setup_windows.ps1
```

You'll be prompted for the device token. The script will install Python
3.12 via winget if missing, then register the agent as a Windows Service.

Verify with:
```powershell
sc query RentablezAgent
Get-Content C:\ProgramData\Rentablez\baseline.json | Select-Object -First 30
Get-Content C:\ProgramData\Rentablez\logs\agent.log -Tail 20
```

## Uninstall

`sudo ./uninstall_mac.sh` or `.\uninstall_windows.ps1`.

These preserve `baseline.json` so reinstalling on the same laptop reuses
the original baseline. To fully wipe (e.g. before reselling), delete the
state directory manually — instructions are printed at the end of the
uninstall.

## Resetting the baseline

If a laptop legitimately had hardware replaced (warranty repair, RAM
upgrade) and you want to re-establish the baseline:

**macOS:**
```bash
sudo rm /var/lib/rentablez/baseline.json
sudo launchctl kickstart -k system/com.rentablez.agent
```

**Windows:**
```powershell
Remove-Item C:\ProgramData\Rentablez\baseline.json
Restart-Service RentablezAgent
```

The next run will write a new baseline and report it to the backend with
`status: "baseline"` (auditable).

## Troubleshooting

| Symptom | Check |
|---|---|
| No reports reaching backend | `tail /var/log/rentablez/agent.log` (or `C:\ProgramData\Rentablez\logs\agent.log`). Look for HTTP errors or `config load failed`. |
| Setup says token format invalid | The regex is `^RTBZ-LAP-\d{5,}$`. The token must match exactly — no extra spaces. |
| Service won't start (macOS) | `sudo launchctl print system/com.rentablez.agent` — look for `last exit code`. |
| Service won't start (Windows) | `Get-EventLog -LogName System -Source "Service Control Manager" -Newest 20` |
| Queue not draining | Check `cat /var/lib/rentablez/queue.json` — `attempts` and `last_attempt_at` show what's been tried. The next boot will retry. |

## Development

Tests are pytest-based. From the repo root:
```bash
python3 -m pytest -v
```

No third-party dependencies are needed for the agent itself — only stdlib.
pytest is dev-only.
```

- [ ] **Step 19.2: Commit**

```bash
git add README.md
git commit -m "docs: warehouse runbook + dev quickstart"
```

---

## Task 20: Final cross-cutting checks

- [ ] **Step 20.1: Run the full test suite one more time**

Run: `python3 -m pytest -v`
Expected: all tests pass. List the count — it should be roughly 60+ tests.

- [ ] **Step 20.2: Confirm no third-party imports in production code**

Run:
```bash
grep -r "^import \|^from " rentablez/ rentablez_agent.py | \
  grep -v "^[^:]*: *from rentablez" | \
  grep -v "^[^:]*: *import \(json\|os\|sys\|re\|logging\|platform\|subprocess\|enum\|urllib\|dataclasses\|datetime\|pathlib\|typing\|time\)"
```
Expected: no output. If any line prints, it's a non-stdlib import that needs to be removed.

- [ ] **Step 20.3: Confirm tree layout matches plan**

Run: `find . -type f -not -path './.git/*' -not -path './__pycache__/*' -not -name '*.pyc' | sort`
Expected output (approximate):
```
./README.md
./com.rentablez.agent.plist
./pyproject.toml
./rentablez/__init__.py
./rentablez/collectors/__init__.py
./rentablez/collectors/mac.py
./rentablez/collectors/windows.py
./rentablez/config.py
./rentablez/diff.py
./rentablez/logger.py
./rentablez/normalize.py
./rentablez/paths.py
./rentablez/queue.py
./rentablez/report.py
./rentablez/runner.py
./rentablez/sender.py
./rentablez_agent.py
./setup_mac.sh
./setup_windows.ps1
./uninstall_mac.sh
./uninstall_windows.ps1
./vendor/README.md
./docs/superpowers/specs/...
./docs/superpowers/plans/...
./tests/__init__.py
./tests/conftest.py
./tests/fixtures/...
./tests/test_*.py
```

- [ ] **Step 20.4: Tag a release**

```bash
git tag -a v1.0.0 -m "Rentablez agent v1.0.0 — initial release"
git log --oneline | head -25
```

- [ ] **Step 20.5: Manual acceptance test plan (not automatable; hand off to QA)**

Document for the QA / warehouse team:

```
1. On a fresh MacBook:
   - sudo ./setup_mac.sh, enter a test token (e.g. RTBZ-LAP-99001)
   - Verify /var/log/rentablez/agent.log shows "agent run complete"
   - Verify backend received a status=baseline report for that token
   - Reboot the laptop
   - Verify backend receives status=ok report for that token after boot
   - Disconnect WiFi, reboot, verify /var/lib/rentablez/queue.json has an
     unsent entry
   - Reconnect WiFi, reboot, verify queue drains and backend gets the report

2. On a fresh Windows laptop:
   - Run setup_windows.ps1 as Admin, enter a test token (e.g. RTBZ-LAP-99002)
   - Verify same checks as macOS, paths translated to C:\ProgramData\Rentablez\

3. Hardware swap test (requires a screwdriver):
   - Setup on a laptop with two RAM slots filled
   - Power off, swap one RAM module for a different stick
   - Power on
   - Verify backend receives status=SWAPPED with changes[] identifying
     ram_modules[N] serial/part_number change

4. Uninstall + reinstall preserves baseline:
   - sudo ./uninstall_mac.sh
   - sudo ./setup_mac.sh (re-enter same token)
   - Verify /var/lib/rentablez/baseline.json contents are unchanged from before
```

---

## Self-Review

(performed against the spec)

**Spec coverage:**
- §4.1 Architecture (one binary, no UI) → Task 13 entrypoint, Task 12 runner orchestrate everything in one process.
- §4.2 Filesystem layout → Task 1 (paths) + Task 15/17 (setup scripts) create them.
- §4.3 Identity (device_token from config) → Task 3 config loader.
- §5 Boot-time flow (diagram) → Task 12 runner implements the exact flow.
- §6.1 Strong-ID fields table → Task 4 diff `_SCALAR_COMPONENTS` and `_LIST_COMPONENTS` match the table.
- §6.2 Weak-ID ignored → Task 4 test `test_weak_id_field_ignored` enforces.
- §6.3 Diff algorithm (incl. normalization) → Task 2 normalize + Task 4 diff.
- §7 Report payload shapes → Task 5 report.
- §8.1–8.4 File formats → Task 3 (config) + Task 12 runner (baseline/current) + Task 6 (queue).
- §9.1 Sending + status classification → Task 7 sender.
- §9.2 Offline behavior (no in-session retry) → Task 12 runner breaks the drain loop on transient failure.
- §9.3 Queue retention rules → Task 6 queue, tests `test_retention_evicts_newest_ok_when_full` and `test_retention_drops_new_ok_when_full_of_critical`.
- §10.1 LaunchDaemon → Task 14 plist.
- §10.2 Windows Service via nssm → Task 17 setup script.
- §11.1 Repo layout → matches the "File Structure" section at the top of this plan and the final tree in Task 20.3.
- §11.2 macOS setup behavior → Task 15.
- §11.3 Windows setup behavior → Task 17.
- §11.4 Operator responsibility → README runbook, Task 19.
- §11.5 Uninstall (preserves baseline) → Tasks 16 + 18.
- §11.6 Trust model → README + the file-permissions chmods in the setup scripts.
- §12 Error handling table → covered by the various exception handlers in runner (corrupt baseline, corrupt queue), sender (HTTP classification), config (loud errors). The "clock wildly wrong" case is implicitly handled by `datetime.now(timezone.utc).isoformat()` — no explicit validation.
- §13.1 Unit tests → Tasks 1–8 each include unit tests.
- §13.2 Integration tests → Task 12 covers all four scenarios (fresh install, second-boot match, second-boot mismatch, offline).
- §13.3 Manual acceptance tests → Task 20.5 documents them.
- §14 Backend contract → No agent code change required; the sender (Task 7) honors the contract.
- §15 Security → File ACLs set in setup scripts; HTTPS via urllib default.
- §16 Out-of-scope items → respected (no auto-update, no tray, etc.).
- §17 Open questions for backend team → noted in spec; not in plan scope.

**Placeholder scan:**
No TBDs, no "implement later", no skipped code. Each task has runnable code and tests.

**Type consistency:**
- `Config` dataclass: device_token, endpoint, installed_at — used consistently in Tasks 3, 12, 13.
- `Change` dataclass: component, field, old, new, reason — used consistently in Tasks 4, 5, 12.
- `SendOutcome` enum: SENT, TRANSIENT_FAILURE, PERMANENT_FAILURE — used consistently in Tasks 7, 12.
- `QueueEntry` dataclass: id, payload, attempts, last_attempt_at, sent — used consistently in Tasks 6, 12.
- Fingerprint dict shape: `machine`, `ram_modules`, `storage`, `battery`, `displays`, `gpus`, `network`, `bluetooth` — used consistently in Tasks 4 (diff schema), 9 (mac collector), 10 (windows collector), 12 (runner integration tests).

No naming drift detected.
