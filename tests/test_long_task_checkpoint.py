"""模块四步骤 2：LayeredMemory checkpoint 命名空间、last_good、乐观锁与进程重启等价（新 DB 连接）。"""

import asyncio
import json

import pytest

from adami_kernel.config import settings
from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.orchestrator.long_task_checkpoint import (
    phase_checkpoint_domain,
    save_phase_checkpoint_with_retry,
    unwrap_phase_payload,
)


@pytest.fixture
def memory_db_path(tmp_path, monkeypatch):
    p = str(tmp_path / "l2_memory.db")
    monkeypatch.setattr(settings, "ADAMI_L2_MEMORY_DB_PATH", p)
    return p


async def _make_memory() -> LayeredMemory:
    m = LayeredMemory()
    await m.initialize(start_periodic_cleanup=False)
    return m


@pytest.mark.asyncio
async def test_restart_new_connection_last_good_and_payload(memory_db_path):
    """新 LayeredMemory 实例 + 同一路径 DB ≈ 内核重启后恢复。"""
    m1 = await _make_memory()
    wf = "wf_restart_demo"
    await m1.save_workflow_phase_checkpoint(
        wf,
        "researcher",
        {"summary": "s1", "sources": [], "status": "success"},
        workflow_state_version=3,
        expected_seq=None,
        update_last_good=True,
    )
    lg1 = await m1.get_last_good_checkpoint(wf)
    assert lg1 is not None
    assert lg1["phase"] == "researcher"
    assert lg1["seq"] == 1
    assert lg1.get("workflow_state_version") == 3

    m2 = await _make_memory()
    lg2 = await m2.get_last_good_checkpoint(wf)
    assert lg2 == lg1
    body = await m2.get_workflow_checkpoint(wf, domain="researcher")
    assert body is not None
    assert body["summary"] == "s1"


@pytest.mark.asyncio
async def test_optimistic_lock_conflict_and_success(memory_db_path):
    m = await _make_memory()
    wf = "wf_lock"
    ph = "researcher"
    r1 = await m.save_workflow_phase_checkpoint(
        wf, ph, {"summary": "a"}, expected_seq=None, update_last_good=True
    )
    assert r1.ok and r1.seq == 1
    bad = await m.save_workflow_phase_checkpoint(
        wf, ph, {"summary": "stale"}, expected_seq=0, update_last_good=True
    )
    assert not bad.ok and bad.conflict and bad.seq == 1
    ok = await m.save_workflow_phase_checkpoint(
        wf, ph, {"summary": "b"}, expected_seq=1, update_last_good=True
    )
    assert ok.ok and ok.seq == 2


@pytest.mark.asyncio
async def test_save_phase_checkpoint_with_retry_after_stale_expected(memory_db_path):
    m = await _make_memory()
    wf = "wf_retry"
    await m.save_workflow_phase_checkpoint(
        wf, "code", {"patch": "1"}, expected_seq=None, update_last_good=False
    )
    # 故意用错误 expected 触发冲突后由重试读取最新再写入
    first = await m.save_workflow_phase_checkpoint(
        wf, "code", {"patch": "bad"}, expected_seq=0, update_last_good=False
    )
    assert first.conflict
    res = await save_phase_checkpoint_with_retry(
        m,
        wf,
        "code",
        {"patch": "ok"},
        workflow_state_version=7,
        update_last_good=True,
        max_retries=4,
    )
    assert res.ok
    rec = await m.get_workflow_phase_checkpoint_record(wf, "code")
    assert rec is not None
    assert unwrap_phase_payload(rec)["patch"] == "ok"
    assert rec["seq"] >= 2


@pytest.mark.asyncio
async def test_legacy_checkpoint_row_still_readable(memory_db_path):
    m = await _make_memory()
    wf = "wf_legacy"
    legacy_domain = "checkpoint_researcher"
    payload = json.dumps({"summary": "from_legacy", "sources": []})
    async with m._db_lock:
        conn = await m._get_conn()
        async with conn.cursor() as c:
            await c.execute(
                "INSERT INTO memories (trace_id, domain, payload, timestamp) VALUES (?, ?, ?, ?)",
                (wf, legacy_domain, payload, __import__("datetime").datetime.now()),
            )
        await conn.commit()
    got = await m.get_workflow_checkpoint(wf, domain="researcher")
    assert got is not None
    assert got["summary"] == "from_legacy"


@pytest.mark.asyncio
async def test_record_checkpoint_failure_independent_of_last_good(memory_db_path):
    m = await _make_memory()
    wf = "wf_fail_meta"
    await m.save_workflow_phase_checkpoint(
        wf, "test", {"r": "ok"}, expected_seq=None, update_last_good=True
    )
    lg_before = await m.get_last_good_checkpoint(wf)
    await m.record_checkpoint_failure(
        wf, failed_phase="iterate", message="boom", workflow_state_version=5
    )
    lg_after = await m.get_last_good_checkpoint(wf)
    assert lg_after == lg_before
    fail = await m.get_latest_checkpoint_failure(wf)
    assert fail is not None
    assert fail["failed_phase"] == "iterate"
    assert "boom" in fail["message"]


@pytest.mark.asyncio
async def test_phase_domain_encoding(memory_db_path):
    wf = "wf_abc12"
    ph = "researcher"
    d = phase_checkpoint_domain(wf, ph)
    assert "wf_abc12" in d and ph in d


@pytest.mark.asyncio
async def test_parallel_retry_both_succeed(memory_db_path):
    """同进程锁串行化；重试策略下并发任务最终均应落盘。"""
    m = await _make_memory()
    wf = "wf_parallel"

    async def one(tag: str):
        return await save_phase_checkpoint_with_retry(
            m,
            wf,
            "research",
            {"tag": tag},
            max_retries=5,
        )

    r_a, r_b = await asyncio.gather(one("a"), one("b"))
    assert r_a.ok and r_b.ok
    rec = await m.get_workflow_phase_checkpoint_record(wf, "research")
    assert rec is not None
    assert rec["seq"] == 2
