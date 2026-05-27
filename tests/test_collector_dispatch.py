from unittest.mock import patch
import pytest
from rentablez.collectors import collect_for_current_os


def test_picks_mac_on_darwin():
    with patch("platform.system", return_value="Darwin"):
        with patch("rentablez.collectors.mac.collect", return_value={"x": "mac"}):
            assert collect_for_current_os()["x"] == "mac"


def test_picks_windows_on_windows():
    with patch("platform.system", return_value="Windows"):
        with patch("rentablez.collectors.windows.collect",
                   return_value={"x": "win"}):
            assert collect_for_current_os()["x"] == "win"


def test_raises_on_unsupported():
    with patch("platform.system", return_value="Linux"):
        with pytest.raises(RuntimeError, match="unsupported"):
            collect_for_current_os()
