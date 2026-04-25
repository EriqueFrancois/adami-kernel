"""
长任务阶段闸（模块四 · 步骤 3）

在 DAG 路由、多 Agent 角色推进、HITL 暂停/恢复时：
- 更新 context.current_phase
- 追加结构化 history（event_type=phase_transition）
- 可选写入 LayeredMemory 阶段 checkpoint
- 向 workflow.events 发布 PHASE_TRANSITION，供 Sim NDJSON 等回放还原阶段序列
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from adami_kernel.config import settings
from adami_kernel.i18n import t
from adami_kernel.nexus.event import AdamiEvent, EventPriority
from adami_kernel.orchestrator.long_task_schema import (
    LongTaskPhase,
    is_long_task_tracking_enabled,
    maybe_initialize_long_task_context,
)
from adami_kernel.orchestrator.workflow_models import Node, WorkflowState

if TYPE_CHECKING:
    from adami_kernel.hippocampus.layered_memory import LayeredMemory
    from adami_kernel.nexus.bus import EventBus

logger = logging.getLogger("AdamI-LongTaskPhaseGate")

HISTORY_EVENT_PHASE = "phase_transition"


def _ltpg_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


def _emit_experience_phase_transition(
    *,
    workflow_id: str,
    from_phase: Optional[str],
    to_phase: str,
    checkpoint_seq: Optional[int],
    gate_detail: str,
    source_module: str,
    reason: str,
) -> None:
    try:
        from adami_kernel.telemetry.experience_sink import get_experience_sink

        get_experience_sink().record_phase_transition(
            trace_id=f"wf_phase_exp_{workflow_id}_{to_phase}",
            episode_id=workflow_id,
            from_phase=from_phase,
            to_phase=to_phase,
            checkpoint_seq=checkpoint_seq,
            gate_detail=gate_detail,
            source_module=source_module,
            reason=reason,
        )
    except Exception as e:
        logger.debug(_ltpg_t("ltpg.debug.exp_skip", e=e))


def long_task_phase_for_workflow_node(node: Node) -> LongTaskPhase:
    """将 DAG 节点类型映射到长任务阶段（运维可按阶段过滤）。"""
    nt = node.node_type
    if nt == "START":
        return LongTaskPhase.RESEARCH
    if nt in ("LLM", "LLM_CALL", "SKILL_CALL"):
        return LongTaskPhase.CODE
    if nt == "TOOL":
        return LongTaskPhase.TEST
    if nt == "DELEGATE_DEERFLOW":
        return LongTaskPhase.RESEARCH
    if nt == "CONDITION":
        return LongTaskPhase.ITERATE
    if nt in ("END", "HUMAN"):
        return LongTaskPhase.DELIVER
    return LongTaskPhase.CODE


def long_task_phase_for_agent_role(role_key: str) -> LongTaskPhase:
    k = (role_key or "").lower()
    if k == "researcher":
        return LongTaskPhase.RESEARCH
    if k == "engineer":
        return LongTaskPhase.CODE
    if k == "executor":
        return LongTaskPhase.TEST
    if k == "critic":
        return LongTaskPhase.ITERATE
    if k == "human":
        return LongTaskPhase.DELIVER
    return LongTaskPhase.CODE


def _history_record(
    *,
    from_phase: Optional[str],
    to_phase: str,
    reason: str,
    source_module: str,
    gate_detail: str,
    workflow_version: int,
    extras: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "event_type": HISTORY_EVENT_PHASE,
        "at": datetime.now(timezone.utc).isoformat(),
        "from_phase": from_phase,
        "to_phase": to_phase,
        "reason": reason,
        "source_module": source_module,
        "gate_detail": gate_detail,
        "workflow_version": workflow_version,
        **extras,
    }


async def _publish_phase_transition(
    bus: Any,
    state: WorkflowState,
    body: Dict[str, Any],
) -> None:
    await bus.publish(
        AdamiEvent(
            trace_id=f"wf_phase_{state.workflow_id}_{int(datetime.now(timezone.utc).timestamp() * 1000)}",
            source_module=str(body.get("source_module", "workflow.phase_gate")),
            target_topic="workflow.events",
            priority=EventPriority.NORMAL,
            payload={
                "workflow_id": state.workflow_id,
                "chat_id": state.chat_id,
                "event_type": "PHASE_TRANSITION",
                **body,
            },
        )
    )


async def emit_phase_transition(
    state: WorkflowState,
    memory: "LayeredMemory",
    bus: Optional["EventBus"],
    *,
    to_phase: LongTaskPhase,
    reason: str,
    source_module: str,
    gate_detail: str = "dag_route",
    write_checkpoint: bool = True,
    history_extras: Optional[Dict[str, Any]] = None,
) -> None:
    """统一阶段闸：history + context + 可选 checkpoint + 可选总线。"""
    if not is_long_task_tracking_enabled(state):
        return
    maybe_initialize_long_task_context(state)
    extras = dict(history_extras or {})
    from_phase = state.context.get("current_phase")
    if not isinstance(from_phase, str):
        from_phase = None

    to_val = to_phase.value if isinstance(to_phase, LongTaskPhase) else str(to_phase)
    ckpt_seq: Optional[int] = None
    if write_checkpoint:
        try:
            ckpt_res = await memory.save_workflow_phase_checkpoint(
                state.workflow_id,
                to_val,
                {
                    "kind": "phase_gate",
                    "gate_detail": gate_detail,
                    "summary": reason[:800],
                    "workflow_version": state.version,
                    **{k: extras[k] for k in ("completed_node_id", "next_node_id") if k in extras},
                },
                workflow_state_version=state.version,
                expected_seq=None,
                update_last_good=True,
            )
            if getattr(ckpt_res, "ok", False):
                ckpt_seq = int(getattr(ckpt_res, "seq", 0))
        except Exception as e:
            logger.warning(_ltpg_t("ltpg.warn.ckpt", e=e))

    rec = _history_record(
        from_phase=from_phase,
        to_phase=to_val,
        reason=reason,
        source_module=source_module,
        gate_detail=gate_detail,
        workflow_version=int(state.version),
        extras=extras,
    )
    if ckpt_seq is not None:
        rec["checkpoint_seq"] = ckpt_seq
    state.history.append(rec)
    state.context["current_phase"] = to_val

    bus_body = {
        "from_phase": from_phase,
        "to_phase": to_val,
        "phase": to_val,
        "checkpoint_seq": ckpt_seq,
        "reason": reason,
        "gate_detail": gate_detail,
        "source_module": source_module,
        "workflow_version": state.version,
        **{
            k: v
            for k, v in extras.items()
            if k in ("completed_node_id", "next_node_id", "agent_role_completed", "agent_role_next")
        },
    }

    if bus is not None:
        try:
            await _publish_phase_transition(bus, state, bus_body)
        except Exception as e:
            logger.warning(_ltpg_t("ltpg.warn.bus", e=e))

    _emit_experience_phase_transition(
        workflow_id=state.workflow_id,
        from_phase=from_phase,
        to_phase=to_val,
        checkpoint_seq=ckpt_seq,
        gate_detail=gate_detail,
        source_module=source_module,
        reason=reason,
    )


async def emit_phase_transition_if_changed(
    state: WorkflowState,
    memory: "LayeredMemory",
    bus: Optional["EventBus"],
    *,
    to_phase: LongTaskPhase,
    reason: str,
    source_module: str,
    gate_detail: str = "dag_route",
    history_extras: Optional[Dict[str, Any]] = None,
) -> None:
    """History 与总线始终记录；checkpoint 在阶段变化或 workflow_terminal / HITL 边界时写入。"""
    if not is_long_task_tracking_enabled(state):
        return
    maybe_initialize_long_task_context(state)
    cur = state.context.get("current_phase")
    to_val = to_phase.value
    write_ckpt = cur != to_val or gate_detail in (
        "workflow_terminal",
        "pre_hitl_pause",
        "post_hitl_resume",
    )
    await emit_phase_transition(
        state,
        memory,
        bus,
        to_phase=to_phase,
        reason=reason,
        source_module=source_module,
        gate_detail=gate_detail,
        write_checkpoint=write_ckpt,
        history_extras=history_extras,
    )


async def checkpoint_hitl_boundary(
    state: WorkflowState,
    memory: "LayeredMemory",
    bus: Optional["EventBus"],
    *,
    kind: str,
    node_id: Optional[str] = None,
    reason: str = "",
    source_module: str = "workflow.engine",
) -> None:
    """
    HITL 暂停前 / 恢复后各落一条 checkpoint。
    kind: pre_hitl_pause | post_hitl_resume
    pre: update_last_good=False；post: update_last_good=True
    """
    if not is_long_task_tracking_enabled(state):
        return
    maybe_initialize_long_task_context(state)
    phase_str = state.context.get("current_phase") or LongTaskPhase.RESEARCH.value
    update_last = kind == "post_hitl_resume"
    ckpt_seq: Optional[int] = None
    try:
        ckpt_res = await memory.save_workflow_phase_checkpoint(
            state.workflow_id,
            phase_str,
            {
                "kind": "hitl_boundary",
                "hitl_kind": kind,
                "node_id": node_id,
                "summary": (reason or kind)[:800],
                "workflow_version": state.version,
            },
            workflow_state_version=state.version,
            expected_seq=None,
            update_last_good=update_last,
        )
        if getattr(ckpt_res, "ok", False):
            ckpt_seq = int(getattr(ckpt_res, "seq", 0))
    except Exception as e:
        logger.warning(_ltpg_t("ltpg.warn.hitl_ckpt", e=e))
    rec = _history_record(
        from_phase=phase_str,
        to_phase=phase_str,
        reason=reason or kind,
        source_module=source_module,
        gate_detail=kind,
        workflow_version=int(state.version),
        extras={"node_id": node_id, "hitl": True},
    )
    if ckpt_seq is not None:
        rec["checkpoint_seq"] = ckpt_seq
    state.history.append(rec)
    if bus is not None:
        try:
            await _publish_phase_transition(
                bus,
                state,
                {
                    "from_phase": phase_str,
                    "to_phase": phase_str,
                    "phase": phase_str,
                    "checkpoint_seq": ckpt_seq,
                    "reason": reason or kind,
                    "gate_detail": kind,
                    "source_module": source_module,
                    "workflow_version": state.version,
                    "node_id": node_id,
                    "hitl": True,
                },
            )
        except Exception as e:
            logger.warning(_ltpg_t("ltpg.warn.hitl_bus", e=e))
    _emit_experience_phase_transition(
        workflow_id=state.workflow_id,
        from_phase=phase_str,
        to_phase=phase_str,
        checkpoint_seq=ckpt_seq,
        gate_detail=kind,
        source_module=source_module,
        reason=reason or kind,
    )


def extract_phase_sequence_from_history(history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """供测试 / 回放工具从 WorkflowState.history 抽取阶段序列。"""
    out: List[Dict[str, Any]] = []
    for h in history:
        if isinstance(h, dict) and h.get("event_type") == HISTORY_EVENT_PHASE:
            row: Dict[str, Any] = {
                "at": h.get("at"),
                "from_phase": h.get("from_phase"),
                "to_phase": h.get("to_phase"),
                "gate_detail": h.get("gate_detail"),
            }
            if h.get("checkpoint_seq") is not None:
                row["checkpoint_seq"] = h.get("checkpoint_seq")
            out.append(row)
    return out
