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
