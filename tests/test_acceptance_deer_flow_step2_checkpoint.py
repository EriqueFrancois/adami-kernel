"""
模块四 · 步骤 2 验收（Checkpoint 策略与 LayeredMemory API）

验收方案（与实现对照）：

1. 命名空间：阶段数据落在 `checkpoint/v1/wf/{workflow_id}/ph/{phase}`（由 `phase_checkpoint_domain` 编码），
   成功写入后可通过 `get_workflow_phase_checkpoint_record` / `get_workflow_checkpoint` 读取业务负载。
2. last_good：成功调用 `save_workflow_phase_checkpoint(..., update_last_good=True)` 后，
   `get_last_good_checkpoint(workflow_id)` 返回 `phase`、`seq`，且可选携带 `workflow_state_version`。
3. 重启等价：使用同一 `l2_memory.db` 路径构造第二个 `LayeredMemory` 实例并 `initialize`，
   last_good 与阶段负载与重启前一致（模拟进程退出后重连）。
4. 乐观锁：`expected_seq` 与库内最新 seq 不一致时返回 `CheckpointSaveResult(conflict=True)` 且 `ok=False`，
   日志由实现侧 `logger.warning` 输出（本用例断言返回值）。
5. 重试策略：`save_phase_checkpoint_with_retry` 在冲突后重读 seq 并最终 `ok=True`。
6. 兼容：旧表 `domain=checkpoint_{phase}` + `trace_id=workflow_id` 的行仍能被 `get_workflow_checkpoint` 读到。
7. 失败元数据：`record_checkpoint_failure` 写入 `last_failure`，且不改变已有 `last_good` 指针语义。

细粒度契约见 `tests/test_long_task_checkpoint.py`；本文件提供一条端到端串联验收。
"""

import json

import pytest

from adami_kernel.config import settings
from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.orchestrator.long_task_checkpoint import (
    phase_checkpoint_domain,
    save_phase_checkpoint_with_retry,
)


@pytest.mark.asyncio
async def test_step2_acceptance_integrated_flow(tmp_path, monkeypatch):
    db = str(tmp_path / "l2_memory.db")
    monkeypatch.setattr(settings, "ADAMI_L2_MEMORY_DB_PATH", db)

    async def open_mem() -> LayeredMemory:
        m = LayeredMemory()
        await m.initialize(start_periodic_cleanup=False)
        return m

    m1 = await open_mem()
    wf = "wf_step2_accept"

    d_research = phase_checkpoint_domain(wf, "researcher")
    assert wf in d_research and "researcher" in d_research

    r_ok = await m1.save_workflow_phase_checkpoint(
        wf,
        "researcher",
        {"summary": "acc-summary", "sources": [], "status": "success"},
        workflow_state_version=42,
        expected_seq=None,
        update_last_good=True,
    )
    assert r_ok.ok and r_ok.seq == 1

    lg = await m1.get_last_good_checkpoint(wf)
    assert lg is not None
    assert lg["phase"] == "researcher" and lg["seq"] == 1
    assert lg.get("workflow_state_version") == 42

    body = await m1.get_workflow_checkpoint(wf, domain="researcher")
    assert body is not None and body["summary"] == "acc-summary"

    # 3) 重启等价
    m2 = await open_mem()
    assert await m2.get_last_good_checkpoint(wf) == lg
    assert (await m2.get_workflow_checkpoint(wf, domain="researcher"))["summary"] == "acc-summary"

    # 4) 乐观锁冲突
    bad = await m2.save_workflow_phase_checkpoint(
        wf, "researcher", {"summary": "stale"}, expected_seq=0, update_last_good=False
    )
    assert not bad.ok and bad.conflict and bad.seq == 1

    # 5) 重试写入另一阶段
    retry_res = await save_phase_checkpoint_with_retry(
        m2,
        wf,
        "code",
        {"files": ["a.py"]},
        workflow_state_version=43,
        update_last_good=True,
        max_retries=4,
    )
    assert retry_res.ok
    lg2 = await m2.get_last_good_checkpoint(wf)
    assert lg2["phase"] == "code" and lg2["seq"] == 1 and lg2.get("workflow_state_version") == 43

    # 6) legacy 可读（另一 workflow）
    wf_old = "wf_legacy_only"
    legacy_domain = "checkpoint_researcher"
    payload = json.dumps({"summary": "legacy-body", "sources": []})
    async with m2._db_lock:
        conn = await m2._get_conn()
        async with conn.cursor() as c:
            await c.execute(
                "INSERT INTO memories (trace_id, domain, payload, timestamp) VALUES (?, ?, ?, ?)",
                (wf_old, legacy_domain, payload, __import__("datetime").datetime.now()),
            )
        await conn.commit()
    leg = await m2.get_workflow_checkpoint(wf_old, domain="researcher")
    assert leg is not None and leg["summary"] == "legacy-body"

    # 7) 失败不推进 last_good（对 wf）
    await m2.record_checkpoint_failure(
        wf, failed_phase="test", message="acceptance-injected", workflow_state_version=44
    )
    lg3 = await m2.get_last_good_checkpoint(wf)
    assert lg3 == lg2
    fail = await m2.get_latest_checkpoint_failure(wf)
    assert fail is not None and fail["failed_phase"] == "test"
