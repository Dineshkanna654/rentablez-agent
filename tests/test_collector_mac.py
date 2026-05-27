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


def test_battery_extracted():
    power = json.loads((FIXTURES / "mac_system_profiler_power.json").read_text())
    runner = _fake_runner({"SPPowerDataType": power})
    fp = collect(runner=runner)
    assert fp["battery"]["serial"] == "BAT-TEST-001"
    assert fp["battery"]["manufacturer"] == "Sony"
    assert fp["battery"]["device_name"] == "bq40z451"
    assert fp["battery"]["cycle_count"] == 142


def test_battery_with_zero_cycle_count_is_preserved():
    """Regression: a brand-new battery with cycle_count=0 must not be
    overwritten by subsequent SPPowerDataType entries (the `or` bug)."""
    runner = _fake_runner({"SPPowerDataType": {
        "SPPowerDataType": [
            {
                "sppower_battery_model_info": {
                    "sppower_battery_serial_number": "NEW-BAT",
                },
                "sppower_battery_health_info": {
                    "sppower_battery_cycle_count": 0,
                },
            },
            {
                # A second entry that should NOT clobber the first's cycle_count
                "sppower_battery_health_info": {
                    "sppower_battery_cycle_count": 999,
                },
            },
        ]
    }})
    fp = collect(runner=runner)
    assert fp["battery"]["cycle_count"] == 0
    assert fp["battery"]["serial"] == "NEW-BAT"


def test_network_mac_extracted():
    net = json.loads((FIXTURES / "mac_system_profiler_network.json").read_text())
    runner = _fake_runner({"SPNetworkDataType": net})
    fp = collect(runner=runner)
    assert len(fp["network"]) == 1
    assert fp["network"][0]["mac"] == "aa:bb:cc:dd:ee:ff"
    assert fp["network"][0]["interface"] == "en0"


def test_bluetooth_address_extracted():
    bt = json.loads((FIXTURES / "mac_system_profiler_bluetooth.json").read_text())
    runner = _fake_runner({"SPBluetoothDataType": bt})
    fp = collect(runner=runner)
    assert fp["bluetooth"]["address"] == "11:22:33:44:55:66"
