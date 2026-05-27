"""Boot-time orchestration: collect → diff → report → queue → drain."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Callable

from rentablez.config import Config
from rentablez.diff import diff_fingerprints
from rentablez.paths import Paths
from rentablez.queue import Queue
from rentablez.report import build_report
from rentablez.sender import SendOutcome

log = logging.getLogger("rentablez")


def _load_baseline(path: str) -> dict | None:
    """Return parsed baseline dict, or None if missing or corrupt."""
    try:
        with open(path) as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        if not isinstance(exc, FileNotFoundError):
            log.warning("Baseline corrupt (%s); treating as missing: %s", path, exc)
        return None


def _atomic_write_json(path: str, data: dict) -> None:
    """Write *data* as JSON to *path* atomically via a temp file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)


def run_once(
    *,
    cfg: Config,
    paths_root: str,
    os_name: str,
    collector: Callable[[], dict],
    sender: Callable[[str, str, dict], SendOutcome],
    os_info: dict,
    now_iso: str | None = None,
) -> None:
    """Execute one full boot-time agent run (spec §5 flow)."""
    paths = Paths(root=paths_root, os_name=os_name)
    os.makedirs(paths.state_dir, exist_ok=True)

    collected_at = now_iso or datetime.now(timezone.utc).isoformat()

    try:
        current_fp = collector()
    except Exception as exc:  # noqa: BLE001
        log.error("Collector failed — skipping this boot run: %s", exc)
        return

    _atomic_write_json(paths.current_file, current_fp)

    baseline = _load_baseline(paths.baseline_file)

    if baseline is None:
        _atomic_write_json(paths.baseline_file, current_fp)
        report = build_report(
            device_token=cfg.device_token, status="baseline",
            fingerprint=current_fp, os_info=os_info,
            changes=None, collected_at=collected_at,
        )
    else:
        changes = diff_fingerprints(baseline, current_fp)
        if changes:
            report = build_report(
                device_token=cfg.device_token, status="SWAPPED",
                fingerprint=current_fp, os_info=os_info,
                changes=changes, collected_at=collected_at,
            )
        else:
            report = build_report(
                device_token=cfg.device_token, status="ok",
                fingerprint=current_fp, os_info=os_info,
                changes=None, collected_at=collected_at,
            )

    queue = Queue(paths.queue_file)
    queue.enqueue(report)

    for entry in queue.unsent():
        outcome = sender(cfg.endpoint, cfg.device_token, entry.payload)
        if outcome in (SendOutcome.SENT, SendOutcome.PERMANENT_FAILURE):
            queue.mark_sent(entry.id)
        else:
            # TRANSIENT_FAILURE: back off, preserve queue order (spec §9.2)
            queue.record_attempt(entry.id)
            break
