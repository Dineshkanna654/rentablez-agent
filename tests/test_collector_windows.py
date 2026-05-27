import json
from pathlib import Path
from rentablez.collectors.windows import collect


FIXTURES = Path(__file__).parent / "fixtures"


def _fake_runner(responses: dict[str, str]):
    """Match a PowerShell snippet to its response by substring."""
    def runner(script: str) -> str:
        for marker, payload in responses.items():
            if marker in script:
                return payload
        return ""
    return runner


def test_machine_fields_extracted():
    machine_json = (FIXTURES / "windows_machine.json").read_text()
    runner = _fake_runner({"Win32_ComputerSystemProduct": machine_json})
    fp = collect(runner=runner)
    assert fp["machine"]["system_serial"] == "C02XK1ABCD12"
    assert fp["machine"]["system_uuid"] == "B8A7F2AA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"
    assert fp["machine"]["vendor"] == "Apple Inc."
    # Canonical keys for diff.py compatibility:
    assert fp["machine"]["serial_number"] == "C02XK1ABCD12"
    assert fp["machine"]["hardware_uuid"] == "B8A7F2AA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"


def test_ram_modules_extracted_with_whitespace_preserved():
    """Collector preserves raw values; normalizer (used by diff) trims them."""
    ram_json = (FIXTURES / "windows_ram.json").read_text()
    runner = _fake_runner({"Win32_PhysicalMemory": ram_json})
    fp = collect(runner=runner)
    assert len(fp["ram_modules"]) == 1
    m = fp["ram_modules"][0]
    assert m["serial"] == "4F2A8B   "          # trailing whitespace preserved
    assert m["part_number"] == "HMA851S6JJR6N-VK   "
    assert m["slot"] == "DIMM0"
    assert m["manufacturer"] == "SK Hynix"


def test_missing_data_yields_empty_sections():
    runner = _fake_runner({})
    fp = collect(runner=runner)
    assert fp["machine"] == {} or all(v is None for v in fp["machine"].values())
    assert fp["ram_modules"] == []
    assert fp["storage"] == []


def test_subprocess_error_handled_gracefully():
    def bad(script):
        raise OSError("powershell missing")
    fp = collect(runner=bad)
    assert isinstance(fp, dict)
    assert "machine" in fp
    assert "ram_modules" in fp


def test_single_item_object_normalized_to_list():
    """PowerShell ConvertTo-Json emits a single object (not a 1-element list)
    when only one match exists. The collector must normalize both shapes."""
    single_ram = json.dumps({
        "BankLabel": "BANK 0", "DeviceLocator": "DIMM0",
        "Manufacturer": "X", "PartNumber": "Y", "SerialNumber": "Z",
        "Capacity": 8589934592, "Speed": 3200, "MemoryType": 26, "FormFactor": 12,
    })
    runner = _fake_runner({"Win32_PhysicalMemory": single_ram})
    fp = collect(runner=runner)
    assert len(fp["ram_modules"]) == 1
    assert fp["ram_modules"][0]["serial"] == "Z"


def test_gpu_vendor_id_extracted_from_pnp_device_id():
    gpu_json = (FIXTURES / "windows_gpu.json").read_text()
    runner = _fake_runner({"Win32_VideoController": gpu_json})
    fp = collect(runner=runner)
    assert len(fp["gpus"]) == 1
    assert fp["gpus"][0]["device_id"] == "PCI\\VEN_8086&DEV_9A49&SUBSYS_220A1043&REV_01\\3&11583659&0&10"
    assert fp["gpus"][0]["vendor_id"] == "8086"
    assert fp["gpus"][0]["vendor"] == "Intel Corporation"


def test_battery_extracted():
    basic = (FIXTURES / "windows_battery_basic.json").read_text()
    static = (FIXTURES / "windows_battery_static.json").read_text()
    cycles = (FIXTURES / "windows_battery_cycles.json").read_text()
    runner = _fake_runner({
        "Win32_Battery": basic,
        "BatteryStaticData": static,
        "BatteryCycleCount": cycles,
    })
    fp = collect(runner=runner)
    assert fp["battery"]["serial"] == "BAT-12345"
    assert fp["battery"]["manufacturer"] == "SMP"
    assert fp["battery"]["device_name"] == "DELL 5JJDDC4"
    assert fp["battery"]["cycle_count"] == 87
