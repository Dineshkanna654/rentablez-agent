#!/usr/bin/env python3
"""Rentablez agent entrypoint.

Invoked at boot by launchd (macOS) or by nssm (Windows). Reads config,
collects hardware, compares against baseline, queues + sends the report,
exits.
"""
from __future__ import annotations

import platform
import sys
from datetime import datetime, timezone

from rentablez.collectors import collect_for_current_os
from rentablez.config import load_config, ConfigError
from rentablez.logger import setup_logger
from rentablez.paths import Paths
from rentablez.runner import run_once
from rentablez.sender import send


def _os_info() -> dict:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "hostname": platform.node(),
    }


def main() -> int:
    paths = Paths.for_current_os()
    logger = setup_logger(paths.log_file)

    try:
        cfg = load_config(paths.config_file)
    except ConfigError as e:
        logger.error("config load failed: %s", e)
        return 1

    logger.info("agent starting (token=%s)", cfg.device_token)

    run_once(
        cfg=cfg,
        paths_root="",
        os_name=platform.system(),
        collector=collect_for_current_os,
        sender=send,
        os_info=_os_info(),
        now_iso=datetime.now(timezone.utc).isoformat(),
    )

    logger.info("agent run complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
