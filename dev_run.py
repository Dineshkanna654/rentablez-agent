#!/usr/bin/env python3
"""Dev-only test runner — no sudo, no LaunchDaemon.

Usage:
    python3 dev_run.py --token <asset_tag> [--endpoint <url>]

Defaults:
    endpoint = http://localhost:9000/api/devices/checkin

All state (baseline, queue, log) is written under /tmp/rentablez-dev/
so nothing touches system directories.
"""
import argparse
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from rentablez.collectors import collect_for_current_os
from rentablez.config import Config
from rentablez.logger import setup_logger
from rentablez.runner import run_once
from rentablez.sender import send

DEV_ROOT = "/tmp/rentablez-dev"
DEFAULT_ENDPOINT = "http://localhost:9000/api/devices/checkin"


def _os_info() -> dict:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "hostname": platform.node(),
    }


def main():
    parser = argparse.ArgumentParser(description="Rentablez agent — dev test run")
    parser.add_argument("--token", required=True, help="asset_tag to use as device token")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help="Checkin endpoint URL")
    parser.add_argument("--reset-baseline", action="store_true", help="Delete saved baseline before running (simulates first boot)")
    args = parser.parse_args()

    state_dir = Path(DEV_ROOT) / "var/lib/rentablez"
    log_dir = Path(DEV_ROOT) / "var/log/rentablez"
    state_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    if args.reset_baseline:
        baseline = state_dir / "baseline.json"
        if baseline.exists():
            baseline.unlink()
            print(f"[dev_run] Removed baseline at {baseline}")

    log_file = str(log_dir / "agent.log")
    logger = setup_logger(log_file)
    logger.info("dev_run starting (token=%s, endpoint=%s)", args.token, args.endpoint)

    cfg = Config(device_token=args.token, endpoint=args.endpoint)

    print(f"[dev_run] token    = {args.token}")
    print(f"[dev_run] endpoint = {args.endpoint}")
    print(f"[dev_run] state    = {DEV_ROOT}")
    print()

    run_once(
        cfg=cfg,
        paths_root=DEV_ROOT,
        os_name=platform.system(),
        collector=collect_for_current_os,
        sender=send,
        os_info=_os_info(),
        now_iso=datetime.now(timezone.utc).isoformat(),
    )

    # Print what was collected
    current_file = state_dir / "current.json"
    if current_file.exists():
        fp = json.loads(current_file.read_text())
        keys = list(fp.keys())
        print(f"[dev_run] fingerprint keys collected: {keys}")

    queue_file = state_dir / "queue.json"
    if queue_file.exists():
        queue = json.loads(queue_file.read_text())
        unsent = [e for e in queue if not e.get("sent")]
        if unsent:
            print(f"[dev_run] {len(unsent)} report(s) still queued (backend may be down)")
        else:
            print(f"[dev_run] all reports sent successfully")

    print(f"\n[dev_run] log: {log_file}")
    print(f"[dev_run] baseline: {state_dir}/baseline.json")


if __name__ == "__main__":
    main()
