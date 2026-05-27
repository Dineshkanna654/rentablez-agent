import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from rentablez.queue import Queue, QueueEntry


def test_enqueue_creates_entry(tmp_path):
    q = Queue(str(tmp_path / "queue.json"))
    q.enqueue({"status": "baseline", "device_token": "T"})
    entries = q.unsent()
    assert len(entries) == 1
    assert entries[0].payload == {"status": "baseline", "device_token": "T"}
    assert entries[0].sent is False
    assert entries[0].attempts == 0


def test_enqueue_persists_across_instances(tmp_path):
    path = str(tmp_path / "queue.json")
    q1 = Queue(path)
    q1.enqueue({"status": "ok"})
    q2 = Queue(path)
    assert len(q2.unsent()) == 1


def test_mark_sent(tmp_path):
    q = Queue(str(tmp_path / "queue.json"))
    q.enqueue({"status": "ok"})
    entry = q.unsent()[0]
    q.mark_sent(entry.id)
    assert q.unsent() == []


def test_increment_attempts(tmp_path):
    q = Queue(str(tmp_path / "queue.json"))
    q.enqueue({"status": "ok"})
    entry = q.unsent()[0]
    q.record_attempt(entry.id)
    refreshed = q.unsent()[0]
    assert refreshed.attempts == 1
    assert refreshed.last_attempt_at is not None


def test_corrupt_file_starts_fresh_and_archives(tmp_path):
    path = tmp_path / "queue.json"
    path.write_text("not json at all {{{")
    q = Queue(str(path))
    assert q.unsent() == []
    broken = list(tmp_path.glob("queue.json.broken-*"))
    assert len(broken) == 1


def test_retention_evicts_newest_ok_when_full(tmp_path):
    """spec §9.3: drop NEWEST ok report when full; never drop baseline/SWAPPED."""
    q = Queue(str(tmp_path / "queue.json"), max_unsent=3)
    q.enqueue({"status": "baseline"})
    q.enqueue({"status": "ok"})       # newest ok at this point
    q.enqueue({"status": "SWAPPED"})  # queue full (3)
    q.enqueue({"status": "ok"})       # triggers eviction of an ok
    statuses = [e.payload["status"] for e in q.unsent()]
    assert "baseline" in statuses
    assert "SWAPPED" in statuses
    assert len(q.unsent()) == 3


def test_retention_drops_new_ok_when_full_of_critical(tmp_path):
    """If queue is full and we'd otherwise have to drop a baseline/SWAPPED,
    drop the new ok instead."""
    q = Queue(str(tmp_path / "queue.json"), max_unsent=2)
    q.enqueue({"status": "baseline"})
    q.enqueue({"status": "SWAPPED"})
    q.enqueue({"status": "ok"})  # cannot evict critical; drop the new one
    statuses = [e.payload["status"] for e in q.unsent()]
    assert statuses == ["baseline", "SWAPPED"]


def test_sent_entries_pruned_after_retention_window(tmp_path):
    """spec §9.3: sent reports pruned 7 days after last_attempt_at."""
    qpath = tmp_path / "queue.json"
    q = Queue(str(qpath))
    q.enqueue({"status": "ok"})
    entry = q.unsent()[0]
    q.mark_sent(entry.id)
    # Force last_attempt_at to 8 days ago and reload
    raw = json.loads(qpath.read_text())
    raw[0]["last_attempt_at"] = (
        datetime.now(timezone.utc) - timedelta(days=8)
    ).isoformat()
    qpath.write_text(json.dumps(raw))
    # Loading the queue should prune the >7-day-old sent entry
    Queue(str(qpath))
    all_raw = json.loads(qpath.read_text())
    assert all_raw == []


def test_atomic_write_no_temp_leftover(tmp_path):
    path = tmp_path / "queue.json"
    q = Queue(str(path))
    q.enqueue({"status": "ok"})
    assert not (tmp_path / "queue.json.tmp").exists()
    data = json.loads(path.read_text())
    assert len(data) == 1
