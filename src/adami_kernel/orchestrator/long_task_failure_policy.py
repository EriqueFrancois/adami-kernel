"""
长任务节点失败分类（模块四 · 步骤 4）

transient：网络抖动、超时等，沿用节点级 error_retry_counts。
phase_fatal：鉴权/沙箱类错误，优先尝试从 last_good 阶段 checkpoint 回滚后继续，而非盲目同节点重试。
"""

from __future__ import annotations

import re
from typing import Literal

from adami_kernel.config import settings
from adami_kernel.orchestrator.workflow_models import Node

FailureClass = Literal["transient", "phase_fatal"]


def _norm_err(error: str) -> str:
    return (error or "").lower()


def classify_workflow_node_failure(node: Node, error: str) -> FailureClass:
    """基于错误串与配置子串匹配；未命中 fatal 则默认为 transient。"""
    e = _norm_err(error)
    fatal_patterns = getattr(
        settings,
        "ADAMI_LONG_TASK_PHASE_FATAL_SUBSTRINGS",
        ["403", "401", "forbidden", "unauthorized", "sandbox violation", "auth failed"],
    )
    for p in fatal_patterns:
        if p and str(p).lower() in e:
            return "phase_fatal"
    transient_boost = getattr(
        settings,
        "ADAMI_LONG_TASK_TRANSIENT_SUBSTRINGS",
        [
            "timeout",
            "timed out",
            "temporarily unavailable",
            "503",
            "502",
            "connection reset",
            "econnreset",
        ],
    )
    for p in transient_boost:
        if p and str(p).lower() in e:
            return "transient"
    # TOOL 节点 + 明确 exit code 类（可选启发式）
    if node.node_type == "TOOL" and re.search(r"\b(exit\s*code|errno)\s*[1-9]", e):
        return "transient"
    return "transient"
