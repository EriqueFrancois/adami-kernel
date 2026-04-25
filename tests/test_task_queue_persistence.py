from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from adami_kernel.core.task_queue import QueuedTask, TaskQueueStore


def test_ttl_drops_stale_pending(tmp_path: Path) -> None:
    p = tmp_path / "tq.json"
    s = TaskQueueStore(p, ttl_sec=10.0, max_per_chat=0, max_total=0)
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
    s2 = TaskQueueStore(p, ttl_sec=10.0, max_per_chat=0, max_total=0)
    assert s2.list_pending("1") == []


def test_drop_oldest_per_chat_cap(tmp_path: Path) -> None:
    p = tmp_path / "tq2.json"
    tq = TaskQueueStore(p, ttl_sec=0.0, max_per_chat=2, max_total=0, overflow_mode="drop_oldest")
    tq.enqueue(chat_id="9", task="a", source_module="user.prompt", platform="cli")
    tq.enqueue(chat_id="9", task="b", source_module="user.prompt", platform="cli")
    tq.enqueue(chat_id="9", task="c", source_module="user.prompt", platform="cli")
    pend = [x.task for x in tq.list_pending("9")]
    assert pend == ["b", "c"]


def test_reject_when_full(tmp_path: Path) -> None:
    p = tmp_path / "tq3.json"
    tq = TaskQueueStore(p, ttl_sec=0.0, max_per_chat=1, max_total=0, overflow_mode="reject")
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
    tq = TaskQueueStore(p, fernet_key=key)
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
    tq = TaskQueueStore(p, ttl_sec=0.0, max_per_chat=0, max_total=0)
    assert tq.list_pending("42")[0].task == "hello"
