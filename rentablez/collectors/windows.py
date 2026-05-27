"""Windows hardware fingerprint collector.

Exposes a single public function: collect(runner=None) -> dict
The runner parameter is injectable for testing; production calls powershell via subprocess.
"""

import json
import re
import subprocess
from typing import Callable


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _default_runner(script: str) -> str:
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=30, check=False,
        )
        return r.stdout or ""
    except (subprocess.SubprocessError, OSError):
        return ""


def _query(runner: Callable[[str], str], script: str):
    """Run a PowerShell script and parse the JSON output. Returns None on failure."""
    try:
        out = runner(script)
        if not out or not out.strip():
            return None
        return json.loads(out)
    except (json.JSONDecodeError, TypeError, ValueError, OSError, subprocess.SubprocessError):
        return None


def _as_list(x):
    """Normalize PowerShell ConvertTo-Json: single object → [obj], list → list."""
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _first_dict(data) -> dict:
    """Return the first dict from a parsed result, or {}."""
    if isinstance(data, list):
        data = data[0] if data else None
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# Section extractors
# ---------------------------------------------------------------------------

def _machine(runner: Callable) -> dict:
    script = ("Get-CimInstance Win32_ComputerSystemProduct | "
               "Select-Object Name,Vendor,Version,IdentifyingNumber,UUID | "
               "ConvertTo-Json -Compress")
    data = _first_dict(_query(runner, script))
    if not data:
        return {
            "vendor": None, "model": None,
            "system_serial": None, "system_uuid": None,
            "serial_number": None, "hardware_uuid": None,
        }
    identifying_number = data.get("IdentifyingNumber")
    uuid = data.get("UUID")
    return {
        "vendor": data.get("Vendor"),
        "model": data.get("Name") or data.get("Version"),
        # Windows-flavoured aliases (kept for backward compat)
        "system_serial": identifying_number,
        "system_uuid": uuid,
        # Canonical keys expected by diff.py's SCALAR_SCHEMA["machine"]
        "serial_number": identifying_number,
        "hardware_uuid": uuid,
    }


def _ram_modules(runner: Callable) -> list[dict]:
    script = ("Get-CimInstance Win32_PhysicalMemory | "
               "Select-Object BankLabel,DeviceLocator,Manufacturer,PartNumber,"
               "SerialNumber,Capacity,Speed,MemoryType,FormFactor | "
               "ConvertTo-Json -Compress")
    return [
        {
            "bank": item.get("BankLabel"),
            "slot": item.get("DeviceLocator"),
            "manufacturer": item.get("Manufacturer"),
            "part_number": item.get("PartNumber"),
            "serial": item.get("SerialNumber"),
            "capacity": item.get("Capacity"),
            "speed": item.get("Speed"),
        }
        for item in _as_list(_query(runner, script))
        if isinstance(item, dict)
    ]


def _storage(runner: Callable) -> list[dict]:
    script = ("Get-PhysicalDisk | "
               "Select-Object FriendlyName,Manufacturer,Model,SerialNumber,"
               "MediaType,BusType,Size,FirmwareVersion | "
               "ConvertTo-Json -Compress")
    return [
        {
            "name": item.get("FriendlyName"),
            "manufacturer": item.get("Manufacturer"),
            "model": item.get("Model"),
            "serial": item.get("SerialNumber"),
            "media_type": item.get("MediaType"),
            "bus_type": item.get("BusType"),
            "size": item.get("Size"),
            "firmware": item.get("FirmwareVersion"),
        }
        for item in _as_list(_query(runner, script))
        if isinstance(item, dict)
    ]


def _battery(runner: Callable) -> dict:
    result: dict = {
        "name": None, "chemistry": None, "design_capacity": None,
        "full_charge_capacity": None, "manufacturer": None,
        "device_name": None, "serial": None, "cycle_count": None,
    }
    basic = _first_dict(_query(runner,
        "Get-CimInstance Win32_Battery | "
        "Select-Object Name,Chemistry,DesignCapacity | ConvertTo-Json -Compress"))
    if basic:
        result["name"] = basic.get("Name")
        result["chemistry"] = basic.get("Chemistry")
        result["design_capacity"] = basic.get("DesignCapacity")

    static = _first_dict(_query(runner,
        "Get-CimInstance -Namespace root\\WMI -ClassName BatteryStaticData | "
        "Select-Object ManufactureName,DeviceName,SerialNumber,"
        "DesignedCapacity,FullChargeCapacity | ConvertTo-Json -Compress"))
    if static:
        # Note: WMI property is literally "ManufactureName" (no trailing 'r')
        result["manufacturer"] = static.get("ManufactureName")
        result["device_name"] = static.get("DeviceName")
        result["serial"] = static.get("SerialNumber")
        if static.get("DesignedCapacity") is not None:
            result["design_capacity"] = static.get("DesignedCapacity")
        result["full_charge_capacity"] = static.get("FullChargeCapacity")

    cycle = _first_dict(_query(runner,
        "Get-CimInstance -Namespace root\\WMI -ClassName BatteryCycleCount | "
        "Select-Object CycleCount | ConvertTo-Json -Compress"))
    if cycle:
        result["cycle_count"] = cycle.get("CycleCount")
    return result


def _displays(runner: Callable) -> list[dict]:
    script = (
        "$monitors = Get-CimInstance -Namespace root\\WMI -ClassName WmiMonitorID; "
        "$monitors | ForEach-Object { "
        "  $mfr = [System.Text.Encoding]::ASCII.GetString($_.ManufacturerName -ne 0); "
        "  $prod = [System.Text.Encoding]::ASCII.GetString($_.ProductCodeID -ne 0); "
        "  $ser = [System.Text.Encoding]::ASCII.GetString($_.SerialNumberID -ne 0); "
        "  [PSCustomObject]@{Manufacturer=$mfr; ProductCode=$prod; Serial=$ser} "
        "} | ConvertTo-Json -Compress"
    )
    return [
        {
            "edid_vendor": item.get("Manufacturer"),
            "edid_product": item.get("ProductCode"),
            "edid_serial": item.get("Serial"),
        }
        for item in _as_list(_query(runner, script))
        if isinstance(item, dict)
    ]


def _parse_vendor_id(pnp_device_id: str | None) -> str | None:
    """Extract the 4-hex-digit vendor ID from a PCI PNPDeviceID string.

    Example: 'PCI\\VEN_8086&DEV_9A49&...' → '8086'
    Returns None if the string is absent or the VEN_ segment is not found.
    """
    if not pnp_device_id:
        return None
    m = re.search(r"VEN_([0-9A-Fa-f]{4})", pnp_device_id)
    return m.group(1) if m else None


def _gpus(runner: Callable) -> list[dict]:
    script = ("Get-CimInstance Win32_VideoController | "
               "Select-Object Name,AdapterCompatibility,VideoProcessor,"
               "DriverVersion,PNPDeviceID,AdapterRAM | ConvertTo-Json -Compress")
    return [
        {
            "name": item.get("Name"),
            "vendor": item.get("AdapterCompatibility"),
            "processor": item.get("VideoProcessor"),
            "driver": item.get("DriverVersion"),
            "device_id": item.get("PNPDeviceID"),
            # Canonical key expected by diff.py's LIST_SCHEMA["gpus"]
            "vendor_id": _parse_vendor_id(item.get("PNPDeviceID")),
            "vram": item.get("AdapterRAM"),
        }
        for item in _as_list(_query(runner, script))
        if isinstance(item, dict)
    ]


def _network(runner: Callable) -> list[dict]:
    script = ("Get-NetAdapter -Physical | "
               "Select-Object Name,InterfaceDescription,MacAddress,Status,LinkSpeed | "
               "ConvertTo-Json -Compress")
    return [
        {
            "name": item.get("Name"),
            "description": item.get("InterfaceDescription"),
            "mac": item.get("MacAddress"),
            "status": item.get("Status"),
            "speed": item.get("LinkSpeed"),
        }
        for item in _as_list(_query(runner, script))
        if isinstance(item, dict)
    ]


def _bluetooth(runner: Callable) -> dict:
    script = ("Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue | "
               "Select-Object DeviceID,FriendlyName,Manufacturer | "
               "ConvertTo-Json -Compress")
    items = _as_list(_query(runner, script))
    first = items[0] if items and isinstance(items[0], dict) else {}
    return {
        "address": first.get("DeviceID"),
        "name": first.get("FriendlyName"),
        "manufacturer": first.get("Manufacturer"),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def collect(runner: Callable[[str], str] | None = None) -> dict:
    """Collect Windows hardware fingerprint.

    Args:
        runner: Optional callable(script: str) -> str.  If None, uses powershell.

    Returns:
        Fingerprint dict with keys: machine, ram_modules, storage, battery,
        displays, gpus, network, bluetooth.
    """
    if runner is None:
        runner = _default_runner
    return {
        "machine": _machine(runner),
        "ram_modules": _ram_modules(runner),
        "storage": _storage(runner),
        "battery": _battery(runner),
        "displays": _displays(runner),
        "gpus": _gpus(runner),
        "network": _network(runner),
        "bluetooth": _bluetooth(runner),
    }
