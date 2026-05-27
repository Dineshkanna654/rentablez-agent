import json
from pathlib import Path
from rentablez.collectors.mac import collect


FIXTURES = Path(__file__).parent / "fixtures"


def _fake_runner(responses: dict):
    """Build a runner that returns the right JSON for each data type."""
    def runner(args):
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
    assert fp["machine"] == {} or all(v is None for v in fp["machine"].values())
    assert fp["storage"] == []
    assert fp["ram_modules"] == []


def test_subprocess_error_does_not_crash():
    def bad_runner(args):
        raise OSError("system_profiler not found")
    fp = collect(runner=bad_runner)
    # Should return a fingerprint with empty sections, not raise
    assert isinstance(fp, dict)
    assert "machine" in fp
