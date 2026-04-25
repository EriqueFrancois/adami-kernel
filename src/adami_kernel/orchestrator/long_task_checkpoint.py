"""
长任务 Checkpoint 命名空间与信封（模块四 · 步骤 2）

逻辑命名空间（落盘在 SQLite `memories.domain` 中编码为路径式字符串）：
  checkpoint/v1/wf/{workflow_id}/ph/{phase}     — 按阶段的版本化 checkpoint 行
  checkpoint/v1/wf/{workflow_id}/meta          — last_good / last_failure 等元数据行

trace_id 存序号或语义键，便于排查；同一 domain 多行时按 id DESC 取最新。
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from adami_kernel.hippocampus.layered_memory import LayeredMemory

logger = logging.getLogger("AdamI-LongTaskCheckpoint")

# 与 memories.domain 中使用的片段一致（勿随意改，否则需迁移脚本）
CHECKPOINT_ROOT = "checkpoint/v1"


@dataclass
class CheckpointSaveResult:
    ok: bool
    seq: int
    conflict: bool = False


def _safe_segment(value: str, max_len: int = 200) -> str:
    """限制 domain 片段字符，避免路径注入或超长。"""
    s = (value or "").strip()
    if not s:
        return "_empty"
    if len(s) > max_len:
        s = s[:max_len]
    if not re.match(r"^[\w\-.:]+$", s):
        return (
            "__hashed__"
            + __import__("hashlib").sha256(value.encode("utf-8", errors="replace")).hexdigest()[:16]
        )
    return s


def phase_checkpoint_domain(workflow_id: str, phase: str) -> str:
    """checkpoint/{workflow_id}/{phase} 的物理编码（domain 列）。"""
    wf = _safe_segment(workflow_id)
    ph = _safe_segment(phase, max_len=64)
    return f"{CHECKPOINT_ROOT}/wf/{wf}/ph/{ph}"


def workflow_checkpoint_meta_domain(workflow_id: str) -> str:
    wf = _safe_segment(workflow_id)
    return f"{CHECKPOINT_ROOT}/wf/{wf}/meta"


def wrap_phase_envelope(
    *,
    seq: int,
    phase: str,
    payload: Dict[str, Any],
    workflow_state_version: Optional[int] = None,
    kind: str = "phase_success",
) -> Dict[str, Any]:
    return {
        "seq": seq,
        "phase": phase,
        "payload": payload,
        "workflow_state_version": workflow_state_version,
        "kind": kind,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }


def unwrap_phase_payload(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """从信封取业务负载；兼容旧格式（整 dict 即负载）。"""
    if not isinstance(envelope, dict):
        return {}
    if "payload" in envelope and isinstance(envelope["payload"], dict):
        return envelope["payload"]
    return envelope


async def save_phase_checkpoint_with_retry(
    memory: "LayeredMemory",
    workflow_id: str,
    phase: str,
    payload_body: Dict[str, Any],
    *,
    workflow_state_version: Optional[int] = None,
    update_last_good: bool = True,
    max_retries: int = 3,
) -> CheckpointSaveResult:
    """
    乐观锁下写入：每次重试前重读最新 seq，冲突时退避重试。
    """
    last: Optional[CheckpointSaveResult] = None
    for attempt in range(max(1, max_retries)):
        rec = await memory.get_workflow_phase_checkpoint_record(workflow_id, phase)
        latest_seq = int(rec["seq"]) if rec and rec.get("seq") is not None else 0
        expected = latest_seq
        last = await memory.save_workflow_phase_checkpoint(
            workflow_id,
            phase,
            payload_body,
            workflow_state_version=workflow_state_version,
            expected_seq=expected,
            update_last_good=update_last_good,
        )
        if last.ok or not last.conflict:
            return last
        logger.warning(
            "[LongTaskCheckpoint] seq 冲突重试 attempt=%s/%s workflow_id=%s phase=%s",
            attempt + 1,
            max_retries,
            workflow_id,
            phase,
        )
        await asyncio.sleep(0.02 * (attempt + 1))
    assert last is not None
    return last
