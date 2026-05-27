"""Persistent JSON queue with retention rules (spec §9.3)."""
import json
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

_CRITICAL = {"baseline", "SWAPPED"}
_RETENTION_DAYS = 7


@dataclass
class QueueEntry:
    id: str
    payload: dict
    attempts: int = 0
    last_attempt_at: Optional[str] = None
    sent: bool = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _entry_from_dict(d: dict) -> QueueEntry:
    return QueueEntry(
        id=d["id"],
        payload=d["payload"],
        attempts=d.get("attempts", 0),
        last_attempt_at=d.get("last_attempt_at"),
        sent=d.get("sent", False),
    )


class Queue:
    def __init__(self, path: str, max_unsent: int = 100) -> None:
        self._path = Path(path)
        self._max_unsent = max_unsent
        self._entries: list[QueueEntry] = []
        self._load()

    # -- Public API ---------------------------------------------------- #

    def enqueue(self, payload: dict) -> None:
        """Append a new entry, applying retention rules if queue is full."""
        if len(self.unsent()) >= self._max_unsent:
            if not self._make_room(payload):
                return  # new entry dropped
        self._entries.append(QueueEntry(id=self._new_id(), payload=payload))
        self._save()

    def unsent(self) -> list[QueueEntry]:
        return [e for e in self._entries if not e.sent]

    def mark_sent(self, entry_id: str) -> None:
        for e in self._entries:
            if e.id == entry_id:
                e.sent = True
                e.last_attempt_at = _now_iso()
                break
        self._save()

    def record_attempt(self, entry_id: str) -> None:
        for e in self._entries:
            if e.id == entry_id:
                e.attempts += 1
                e.last_attempt_at = _now_iso()
                break
        self._save()

    # -- Retention helpers --------------------------------------------- #

    def _make_room(self, incoming: dict) -> bool:
        """Try to make room for *incoming*. Return True if room was made,
        False if the incoming payload should be silently dropped."""
        unsent = self.unsent()
        status = incoming.get("status", "")

        # Find the newest (highest index in self._entries) ok entry
        newest_ok_idx = None
        for i in range(len(self._entries) - 1, -1, -1):
            e = self._entries[i]
            if not e.sent and e.payload.get("status", "") not in _CRITICAL:
                newest_ok_idx = i
                break

        if newest_ok_idx is not None:
            # Case 1: evict the newest non-critical unsent entry
            self._entries.pop(newest_ok_idx)
            return True

        # No ok entry to evict — all unsent are critical
        if status not in _CRITICAL:
            # Case 2: incoming is ok and there's no room → drop it
            return False

        # Case 3: incoming is critical and all unsent are critical → evict newest
        for i in range(len(self._entries) - 1, -1, -1):
            e = self._entries[i]
            if not e.sent:
                self._entries.pop(i)
                return True

        return True  # shouldn't reach here; queue has room somehow

    # -- Persistence helpers ------------------------------------------- #

    def _new_id(self) -> str:
        # Monotonic: ISO timestamp + counter suffix avoids collisions
        return f"{datetime.now(timezone.utc).isoformat()}-{time.monotonic_ns()}"

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text())
            self._entries = [_entry_from_dict(d) for d in raw]
        except (json.JSONDecodeError, KeyError, TypeError):
            broken = self._path.with_name(
                f"{self._path.name}.broken-{int(time.time())}"
            )
            self._path.rename(broken)
            self._entries = []
            self._save()
            return
        # Prune sent entries older than retention window
        cutoff = datetime.now(timezone.utc) - timedelta(days=_RETENTION_DAYS)
        before = len(self._entries)
        kept = []
        for e in self._entries:
            if e.sent and e.last_attempt_at is not None:
                try:
                    ts = datetime.fromisoformat(e.last_attempt_at)
                    if ts < cutoff:
                        continue  # prune this entry
                except (ValueError, TypeError):
                    pass  # malformed timestamp — keep the entry, treat as not expired
            kept.append(e)
        self._entries = kept
        if len(self._entries) != before:
            self._save()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps([asdict(e) for e in self._entries]))
        os.replace(tmp, self._path)
