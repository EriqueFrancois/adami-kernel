from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from adami_kernel.core.task_queue import QueuedTask, TaskQueueStore


def test_ttl_drops_stale_pending(tmp_path: Path) -> None:
    p = tmp_path / "tq.json"
    s = TaskQueueStore(p, ttl_sec=10.0, in_progress_ttl_sec=0.0, max_per_chat=0, max_total=0)
    old = time.time() - 3600.0
    s._queues["1"] = [
        QueuedTask(
            id="a",
            task="t",
            chat_id="1",
            source_module="user.prompt",
            platform="cli",
            created_at=old,
        )
    ]
    s._save()
    s2 = TaskQueueStore(p, ttl_sec=10.0, in_progress_ttl_sec=0.0, max_per_chat=0, max_total=0)
    assert s2.list_pending("1") == []


def test_drop_oldest_per_chat_cap(tmp_path: Path) -> None:
    p = tmp_path / "tq2.json"
    tq = TaskQueueStore(
        p,
        ttl_sec=0.0,
        in_progress_ttl_sec=0.0,
        max_per_chat=2,
        max_total=0,
        overflow_mode="drop_oldest",
    )
    tq.enqueue(chat_id="9", task="a", source_module="user.prompt", platform="cli")
    tq.enqueue(chat_id="9", task="b", source_module="user.prompt", platform="cli")
    tq.enqueue(chat_id="9", task="c", source_module="user.prompt", platform="cli")
    pend = [x.task for x in tq.list_pending("9")]
    assert pend == ["b", "c"]


def test_reject_when_full(tmp_path: Path) -> None:
    p = tmp_path / "tq3.json"
    tq = TaskQueueStore(
        p,
        ttl_sec=0.0,
        in_progress_ttl_sec=0.0,
        max_per_chat=1,
        max_total=0,
        overflow_mode="reject",
    )
    assert (
        tq.enqueue(chat_id="9", task="a", source_module="user.prompt", platform="cli") is not None
    )
    assert tq.enqueue(chat_id="9", task="b", source_module="user.prompt", platform="cli") is None
    assert len(tq.list_pending("9")) == 1


def test_fernet_roundtrip(tmp_path: Path) -> None:
    pytest.importorskip("cryptography")
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode("ascii")
    p = tmp_path / "tq4.json"
    tq = TaskQueueStore(p, fernet_key=key, in_progress_ttl_sec=0.0)
    tq.enqueue(
        chat_id="1", task="secret-task", source_module="sensory.telegram", platform="telegram"
    )
    raw = p.read_text(encoding="utf-8")
    outer = json.loads(raw)
    assert outer.get("format") == "adami_task_queue/v2"
    assert "secret-task" not in raw
    tq2 = TaskQueueStore(p, fernet_key=key)
    assert len(tq2.list_pending("1")) == 1
    assert tq2.list_pending("1")[0].task == "secret-task"


def test_plaintext_v1_still_loads(tmp_path: Path) -> None:
    p = tmp_path / "tq5.json"
    payload = {
        "version": 1,
        "queues": {
            "42": [
                {
                    "id": "q_1",
                    "task": "hello",
                    "chat_id": "42",
                    "source_module": "user.prompt",
                    "platform": "cli",
                    "created_at": time.time(),
                }
            ]
        },
        "in_progress": {},
        "saved_at": time.time(),
    }
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tq = TaskQueueStore(p, ttl_sec=0.0, in_progress_ttl_sec=0.0, max_per_chat=0, max_total=0)
    assert tq.list_pending("42")[0].task == "hello"


def test_in_progress_ttl_drops_stale_running(tmp_path: Path) -> None:
    p = tmp_path / "tq_ip.json"
    tq = TaskQueueStore(p, ttl_sec=0.0, in_progress_ttl_sec=10.0, max_per_chat=0, max_total=0)
    old = time.time() - 3600.0
    tq._in_progress["c"] = tq._in_progress.get("c") or None  # type: ignore[assignment]
    # Inject stale row via raw payload to avoid relying on internal types beyond public fields.
    payload = {
        "version": 1,
        "queues": {},
        "in_progress": {
            "c": {
                "id": "run_1",
                "task": "stuck",
                "chat_id": "c",
                "source_module": "user.prompt",
                "platform": "telegram",
                "started_at": old,
                "trace_id": "t1",
            }
        },
        "saved_at": time.time(),
    }
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tq2 = TaskQueueStore(p, ttl_sec=0.0, in_progress_ttl_sec=10.0, max_per_chat=0, max_total=0)
    assert tq2.get_in_progress("c") is None


def test_recover_in_progress_preserves_trace_id(tmp_path: Path) -> None:
    p = tmp_path / "tq_recover.json"
    started = time.time()
    payload = {
        "version": 1,
        "queues": {},
        "in_progress": {
            "c": {
                "id": "run_1",
                "task": "stuck",
                "chat_id": "c",
                "source_module": "user.prompt",
                "platform": "discord",
                "started_at": started,
                "trace_id": "trace-stuck-1",
            }
        },
        "saved_at": time.time(),
    }
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tq2 = TaskQueueStore(p, ttl_sec=0.0, in_progress_ttl_sec=0.0, max_per_chat=0, max_total=0)
    it = tq2.recover_in_progress_to_front("c")
    assert it is not None
    assert it.task == "stuck"
    assert it.trace_id == "trace-stuck-1"
    assert it.recovered_from
    pend = tq2.list_pending("c")
    assert pend and pend[0].trace_id == "trace-stuck-1"
    assert pend[0].recovered_from
    assert pend[0].created_at == pytest.approx(started, abs=1.0)


def test_recovered_in_progress_still_expires_by_pending_ttl(tmp_path: Path) -> None:
    p = tmp_path / "tq_recover_ttl.json"
    old = time.time() - 7200.0
    payload = {
        "version": 1,
        "queues": {},
        "in_progress": {
            "c": {
                "id": "run_1",
                "task": "stuck",
                "chat_id": "c",
                "source_module": "user.prompt",
                "platform": "telegram",
                "started_at": old,
                "trace_id": "t1",
            }
        },
        "saved_at": time.time(),
    }
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tq = TaskQueueStore(p, ttl_sec=3600.0, in_progress_ttl_sec=0.0, max_per_chat=0, max_total=0)
    it = tq.recover_in_progress_to_front("c")
    assert it is not None
    assert it.created_at == pytest.approx(old, abs=1.0)
    assert tq.list_pending("c") == []


def test_settings_default_pending_ttl_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from adami_kernel.config import Settings

    for k in (
        "ADAMI_TASK_QUEUE_TTL_SEC",
        "ADAMI_MESSENGER_NOTIFY_BOOT",
        "ADAMI_TASK_QUEUE_NOTIFY_ON_BOOT",
        "ADAMI_TELEGRAM_DROP_PENDING_UPDATES",
    ):
        monkeypatch.delenv(k, raising=False)
    s = Settings(_env_file=())
    assert float(s.ADAMI_TASK_QUEUE_TTL_SEC) > 0
    assert s.ADAMI_MESSENGER_NOTIFY_BOOT is False
    assert s.ADAMI_TASK_QUEUE_NOTIFY_ON_BOOT is False
    assert s.ADAMI_TELEGRAM_DROP_PENDING_UPDATES is True
