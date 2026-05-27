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


def test_case_difference_in_hex_mac_address():
    """MAC addresses contain colons so are not 'pure hex' per the normalizer;
    case differences therefore ARE flagged. Documented behavior."""
    base = _baseline()
    base["bluetooth"]["address"] = "aa:bb:cc:dd:ee:ff"
    cur = _baseline()
    cur["bluetooth"]["address"] = "AA:BB:CC:DD:EE:FF"
    changes = diff_fingerprints(base, cur)
    assert len(changes) == 1


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
