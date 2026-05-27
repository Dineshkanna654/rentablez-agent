import json
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
    sent_payloads = []

    def sender(endpoint, token, payload):
        sent_payloads.append(payload)
        return SendOutcome.SENT

    run_once(
        cfg=_cfg(),
        paths_root=str(tmp_path),
        os_name="Darwin",
        collector=lambda: fp,
        sender=sender,
        os_info={"system": "Darwin"},
        now_iso="2026-05-26T10:00:00Z",
    )

    baseline_path = tmp_path / "var/lib/rentablez/baseline.json"
    assert baseline_path.exists()
    saved = json.loads(baseline_path.read_text())
    assert saved == fp

    assert len(sent_payloads) == 1
    assert sent_payloads[0]["status"] == "baseline"
    assert sent_payloads[0]["fingerprint"] == fp


def test_second_boot_no_swap_sends_ok(tmp_path):
    fp = _baseline_fp()
    sent_payloads = []

    def sender(endpoint, token, payload):
        sent_payloads.append(payload)
        return SendOutcome.SENT

    run_once(
        cfg=_cfg(), paths_root=str(tmp_path), os_name="Darwin",
        collector=lambda: fp, sender=sender,
        os_info={"system": "Darwin"}, now_iso="2026-05-26T10:00:00Z",
    )
    sent_payloads.clear()

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

    run_once(
        cfg=_cfg(), paths_root=str(tmp_path), os_name="Darwin",
        collector=lambda: base_fp, sender=sender,
        os_info={"system": "Darwin"}, now_iso="2026-05-26T10:00:00Z",
    )
    sent_payloads.clear()

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
    online = [False]
    sent_payloads = []

    def sender(endpoint, token, payload):
        if not online[0]:
            return SendOutcome.TRANSIENT_FAILURE
        sent_payloads.append(payload)
        return SendOutcome.SENT

    # Boot 1 - offline
    run_once(
        cfg=_cfg(), paths_root=str(tmp_path), os_name="Darwin",
        collector=lambda: fp, sender=sender,
        os_info={"system": "Darwin"}, now_iso="2026-05-26T10:00:00Z",
    )
    # Boot 2 - still offline
    run_once(
        cfg=_cfg(), paths_root=str(tmp_path), os_name="Darwin",
        collector=lambda: fp, sender=sender,
        os_info={"system": "Darwin"}, now_iso="2026-05-27T10:00:00Z",
    )
    # Boot 3 - online, drain
    online[0] = True
    run_once(
        cfg=_cfg(), paths_root=str(tmp_path), os_name="Darwin",
        collector=lambda: fp, sender=sender,
        os_info={"system": "Darwin"}, now_iso="2026-05-28T10:00:00Z",
    )

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


def test_collector_exception_does_not_crash(tmp_path):
    """If the collector itself raises, the agent logs and exits cleanly
    without sending anything (per spec §12 error handling)."""
    def bad_collector():
        raise RuntimeError("subprocess failed")

    sent = []
    run_once(
        cfg=_cfg(), paths_root=str(tmp_path), os_name="Darwin",
        collector=bad_collector,
        sender=lambda *a: sent.append("would-have-sent") or SendOutcome.SENT,
        os_info={"system": "Darwin"}, now_iso="2026-05-26T10:00:00Z",
    )
    # No report sent
    assert sent == []
