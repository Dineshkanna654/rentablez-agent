"""macOS hardware fingerprint collector.

Exposes a single public function: collect(runner=None) -> dict
The runner parameter is injectable for testing; production uses system_profiler.
"""

import json
import subprocess
from typing import Callable


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _default_runner(args: list[str]) -> str:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=30, check=False)
        return r.stdout or "{}"
    except (subprocess.SubprocessError, OSError):
        return "{}"


def _profile(runner: Callable[[list[str]], str], data_type: str) -> dict:
    """Call system_profiler for *data_type* and return the parsed JSON."""
    try:
        out = runner(["system_profiler", data_type, "-json"])
        return json.loads(out) if out else {}
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError, TypeError):
        return {}


def _set_if_unset(d: dict, key: str, value) -> None:
    """Set d[key] = value only when d[key] is currently None and value is not None."""
    if d.get(key) is None and value is not None:
        d[key] = value


# ---------------------------------------------------------------------------
# Section extractors
# ---------------------------------------------------------------------------

def _machine(runner: Callable) -> dict:
    data = _profile(runner, "SPHardwareDataType")
    entries = data.get("SPHardwareDataType") or []
    if not entries:
        return {
            "serial_number": None,
            "hardware_uuid": None,
            "model_name": None,
            "model_identifier": None,
            "chip": None,
        }
    hw = entries[0]
    return {
        "serial_number": hw.get("serial_number"),
        "hardware_uuid": hw.get("platform_UUID"),
        "model_name": hw.get("machine_name"),
        "model_identifier": hw.get("machine_model"),
        "chip": hw.get("chip_type") or hw.get("cpu_type"),
    }


def _ram_modules(runner: Callable) -> list[dict]:
    data = _profile(runner, "SPMemoryDataType")
    entries = data.get("SPMemoryDataType") or []
    modules: list[dict] = []
    for entry in entries:
        items = entry.get("_items") or [entry]
        for item in items:
            modules.append({
                "slot": item.get("_name"),
                "size": item.get("dimm_size"),
                "type": item.get("dimm_type"),
                "speed": item.get("dimm_speed"),
                "manufacturer": item.get("dimm_manufacturer"),
                "part_number": item.get("dimm_part_number"),
                "serial": item.get("dimm_serial_number"),
            })
    return modules


def _storage(runner: Callable) -> list[dict]:
    disks: list[dict] = []
    for data_type in ("SPNVMeDataType", "SPSerialATADataType"):
        data = _profile(runner, data_type)
        controllers = data.get(data_type) or []
        for ctrl in controllers:
            for dev in (ctrl.get("_items") or []):
                disks.append({
                    "name": dev.get("_name"),
                    "model": dev.get("device_model") or dev.get("_name"),
                    "serial": dev.get("device_serial"),
                    "revision": dev.get("device_revision"),
                    "size": dev.get("size"),
                })
    return disks


def _battery(runner: Callable) -> dict:
    data = _profile(runner, "SPPowerDataType")
    entries = data.get("SPPowerDataType") or []
    result: dict = {
        "manufacturer": None,
        "device_name": None,
        "serial": None,
        "firmware": None,
        "cycle_count": None,
        "condition": None,
    }
    for entry in entries:
        model_info = entry.get("sppower_battery_model_info") or {}
        _set_if_unset(result, "manufacturer", model_info.get("sppower_battery_manufacturer"))
        _set_if_unset(result, "device_name", model_info.get("sppower_battery_device_name"))
        _set_if_unset(result, "serial", model_info.get("sppower_battery_serial_number"))
        _set_if_unset(result, "firmware", model_info.get("sppower_battery_firmware_version"))

        health_info = entry.get("sppower_battery_health_info") or {}
        _set_if_unset(result, "cycle_count", health_info.get("sppower_battery_cycle_count"))
        _set_if_unset(result, "condition", health_info.get("sppower_battery_health"))
    return result


def _displays_and_gpus(runner: Callable) -> tuple[list[dict], list[dict]]:
    data = _profile(runner, "SPDisplaysDataType")
    entries = data.get("SPDisplaysDataType") or []
    gpus: list[dict] = []
    displays: list[dict] = []
    for entry in entries:
        gpus.append({
            "model": entry.get("sppci_model"),
            "vendor": entry.get("sppci_vendor"),
            "device_id": entry.get("sppci_device_id"),
            "vendor_id": entry.get("sppci_vendor_id"),
            "vram": entry.get("sppci_vram"),
        })
        for disp in (entry.get("spdisplays_ndrvs") or []):
            displays.append({
                "name": disp.get("_name"),
                "edid_vendor": disp.get("_spdisplays_display-vendor-id"),
                "edid_product": disp.get("_spdisplays_display-product-id"),
                "edid_serial": disp.get("_spdisplays_display-serial-number"),
            })
    return displays, gpus


def _network(runner: Callable) -> list[dict]:
    data = _profile(runner, "SPNetworkDataType")
    entries = data.get("SPNetworkDataType") or []
    result: list[dict] = []
    for entry in entries:
        ethernet = entry.get("Ethernet") or {}
        result.append({
            "name": entry.get("_name"),
            "interface": entry.get("interface"),
            "type": entry.get("type"),
            "hardware": entry.get("hardware"),
            "mac": ethernet.get("MAC Address"),
        })
    return result


def _bluetooth(runner: Callable) -> dict:
    data = _profile(runner, "SPBluetoothDataType")
    entries = data.get("SPBluetoothDataType") or []
    result: dict = {"address": None, "chipset": None, "firmware": None}
    if not entries:
        return result
    ctrl = entries[0].get("controller_properties") or {}
    result["address"] = ctrl.get("controller_address")
    result["chipset"] = ctrl.get("controller_chipset")
    result["firmware"] = ctrl.get("controller_firmwareVersion")
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def collect(runner: Callable[[list[str]], str] | None = None) -> dict:
    """Collect macOS hardware fingerprint.

    Args:
        runner: Optional callable(args) -> str.  If None, uses system_profiler.

    Returns:
        Fingerprint dict with keys: machine, ram_modules, storage, battery,
        displays, gpus, network, bluetooth.
    """
    if runner is None:
        runner = _default_runner

    displays, gpus = _displays_and_gpus(runner)

    return {
        "machine": _machine(runner),
        "ram_modules": _ram_modules(runner),
        "storage": _storage(runner),
        "battery": _battery(runner),
        "displays": displays,
        "gpus": gpus,
        "network": _network(runner),
        "bluetooth": _bluetooth(runner),
    }
