"""
阶段 checkpoint 回滚与 HITL 重放（模块四 · 步骤 4 / 4.1）
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional

from adami_kernel.orchestrator.long_task_checkpoint import unwrap_phase_payload
from adami_kernel.orchestrator.long_task_schema import is_long_task_tracking_enabled

if TYPE_CHECKING:
    from adami_kernel.hippocampus.layered_memory import LayeredMemory
    from adami_kernel.orchestrator.workflow_models import WorkflowState

logger = logging.getLogger("AdamI-LongTaskRecovery")


def failure_audit_record(
    *,
    node_id: str,
    error: str,
    failure_class: str,
    retries_at_failure: int,
    recovery_action: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "event_type": "workflow_node_failure",
        "at": datetime.now(timezone.utc).isoformat(),
        "node_id": node_id,
        "error": (error or "")[:2000],
        "failure_class": failure_class,
        "retries_at_failure": retries_at_failure,
        "recovery_action": recovery_action,
        **(extra or {}),
    }


async def rollback_to_last_good_checkpoint(
    state: "WorkflowState",
    memory: "LayeredMemory",
) -> bool:
    """
    将 context 对齐到 last_good 指针所指阶段的最新 checkpoint 负载。
    不修改 phase_recovery_count（由调用方在成功后递增）。
    """
    if not is_long_task_tracking_enabled(state):
        return False
    lg = await memory.get_last_good_checkpoint(state.workflow_id)
    if not lg:
        logger.info("[LongTaskRecovery] 无 last_good，跳过回滚 workflow_id=%s", state.workflow_id)
        return False
    phase = lg.get("phase")
    if not phase or not isinstance(phase, str):
        return False
    rec = await memory.get_workflow_phase_checkpoint_record(state.workflow_id, phase)
    if not rec:
        return False
    payload = unwrap_phase_payload(rec)
    if not isinstance(payload, dict):
        return False
    state.context["current_phase"] = phase
    state.context["phase_recovery_payload"] = payload
    state.context["phase_recovery_from_seq"] = rec.get("seq")
    logger.info(
        "[LongTaskRecovery] 已回滚到 last_good phase=%s seq=%s workflow_id=%s",
        phase,
        rec.get("seq"),
        state.workflow_id,
    )
    return True


async def apply_replay_from_phase_checkpoint(
    state: "WorkflowState",
    memory: "LayeredMemory",
    phase: str,
) -> bool:
    """
    步骤 4.1：按指定阶段加载最新 checkpoint 到 context，并打重做标记（供 Agent 跳过缓存等）。
    """
    if not phase or not is_long_task_tracking_enabled(state):
        return False
    rec = await memory.get_workflow_phase_checkpoint_record(state.workflow_id, phase)
    if not rec:
        logger.warning(
            "[LongTaskRecovery] replay 无 checkpoint workflow_id=%s phase=%s",
            state.workflow_id,
            phase,
        )
        return False
    payload = unwrap_phase_payload(rec)
    if not isinstance(payload, dict):
        return False
    state.context["current_phase"] = phase
    state.context[f"checkpoint_replay_{phase}"] = payload
    state.context["long_task_redo_marker"] = True
    redo = state.context.setdefault("long_task_replay_phases", [])
    if isinstance(redo, list) and phase not in redo:
        redo.append(phase)
    state.history.append(
        {
            "event_type": "hitl_replay_from_phase",
            "at": datetime.now(timezone.utc).isoformat(),
            "replay_phase": phase,
            "checkpoint_seq": rec.get("seq"),
        }
    )
    logger.info(
        "[LongTaskRecovery] HITL replay_from_phase=%s workflow_id=%s",
        phase,
        state.workflow_id,
    )
    return True
