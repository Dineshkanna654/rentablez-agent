"""Dispatcher that picks the right hardware collector for the current OS."""
from __future__ import annotations

import platform


def collect_for_current_os() -> dict:
    system = platform.system()
    if system == "Darwin":
        from rentablez.collectors import mac
        return mac.collect()
    if system == "Windows":
        from rentablez.collectors import windows
        return windows.collect()
    raise RuntimeError(f"unsupported OS: {system}")
