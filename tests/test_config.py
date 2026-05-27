import json
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
