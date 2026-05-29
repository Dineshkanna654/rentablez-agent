import pytest
from rentablez.diff import Change
from rentablez.report import build_report, AGENT_VERSION


def test_baseline_report_shape():
    fp = {"machine": {"serial_number": "S1"}}
    os_info = {"system": "Darwin", "release": "23.0"}
    r = build_report(
        status="baseline",
        fingerprint=fp,
        os_info=os_info,
        changes=None,
        collected_at="2026-05-26T10:00:00Z",
    )
    assert r["agent_version"] == AGENT_VERSION
    assert r["collected_at"] == "2026-05-26T10:00:00Z"
    assert r["status"] == "baseline"
    assert r["fingerprint"] == fp
    assert r["os"] == os_info
    assert "changes" not in r
    assert "current_fingerprint" not in r
    assert "device_token" not in r


def test_ok_report_shape_omits_fingerprint():
    """spec §7.2: ok reports do NOT include full fingerprint."""
    fp = {"machine": {"serial_number": "S1"}}
    r = build_report(
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
    with pytest.raises(ValueError, match="status"):
        build_report(
            status="weird",
            fingerprint={},
            os_info={},
            changes=None,
            collected_at="2026-05-27T08:14:00Z",
        )


def test_swapped_requires_changes():
    with pytest.raises(ValueError, match="changes"):
        build_report(
            status="SWAPPED",
            fingerprint={},
            os_info={},
            changes=None,
            collected_at="2026-05-27T08:14:00Z",
        )
