# 文件路径：src/adami_kernel/telemetry/experience_sink.py
"""经验池采集入口（与 Agent Lightning 解耦）：队列/锁批量入 Aggregator，按 Episode 收口落盘。"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from adami_kernel.config import settings
from adami_kernel.telemetry.experience_aggregator import ExperienceAggregator

logger = logging.getLogger("AdamI-ExperienceSink")

# ---------------------------------------------------------------------------
# Context：长会话（决策 / 工作流）内复用同一 episode_id
# ---------------------------------------------------------------------------
experience_episode_id_ctx: ContextVar[Optional[str]] = ContextVar(
    "experience_episode_id", default=None
)
experience_primary_trace_ctx: ContextVar[Optional[str]] = ContextVar(
    "experience_primary_trace", default=None
)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class ExperienceRecord(BaseModel):
    """单条采集记录（落盘至 Episode.events；不含明文密钥）。"""

    ts: float = Field(default_factory=lambda: time.time())
    trace_id: str
    episode_id: str
    turn_index: int = -1  # 由 Aggregator 覆盖
    type: str  # llm_turn | tool_call | feedback | phase_transition
    payload: Dict[str, Any] = Field(default_factory=dict)
    payload_sha256: str = ""
    phase: Optional[str] = Field(
        default=None,
        description="模块四：阶段闸目标阶段（与 Sim trace 的 phase 对齐）",
    )
    checkpoint_seq: Optional[int] = Field(
        default=None,
        description="模块四：关联的阶段 checkpoint 序号",
    )


# ---------------------------------------------------------------------------
# 脱敏与摘要
# ---------------------------------------------------------------------------
_RE_SK = re.compile(r"sk-[a-zA-Z0-9]{20,}", re.I)
_RE_BEARER = re.compile(r"Bearer\s+[\w\-\._~\+/]+=*", re.I)
_RE_APIKEY = re.compile(r"(?:api[_-]?key|token|secret)\s*[:=]\s*[\"']?[\w\-]{8,}", re.I)
_RE_PWD = re.compile(r"(password|passwd|pwd|密码)\s*[:=]\s*\S+", re.I)


def redact_text(text: str, max_len: int = 2000) -> str:
    if not text:
        return ""
    t = str(text).replace("\r", " ").replace("\n", " ")
    t = re.sub(r"\s+", " ", t).strip()
    t = _RE_SK.sub("[REDACTED_KEY]", t)
    t = _RE_APIKEY.sub("credential=[REDACTED]", t)
    t = _RE_BEARER.sub("Bearer [REDACTED]", t)
    t = _RE_PWD.sub(r"\1=[REDACTED]", t)
    if len(t) > max_len:
        t = t[: max_len - 1] + "…"
    return t


def summarize_text(text: str, head: int = 400) -> str:
    return redact_text(text, max_len=head)


def redact_payload(obj: Any) -> Any:
    """递归脱敏 dict/list 与字符串；用于 payload 与 metadata。"""
    sensitive_keys = frozenset(
        k.lower()
        for k in (
            "api_key",
            "apikey",
            "authorization",
            "password",
            "secret",
            "token",
            "access_token",
            "refresh_token",
            "openai_api_key",
            "anthropic_api_key",
            "bearer",
        )
    )

    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            lk = str(k).lower()
            if lk in sensitive_keys:
                out[k] = "[REDACTED]"
            elif lk == "image_base64" or lk.endswith("_b64"):
                out[k] = f"[REDACTED_B64 len={len(str(v))}]"
            else:
                out[k] = redact_payload(v)
        return out
    if isinstance(obj, list):
        return [redact_payload(x) for x in obj[:200]]
    if isinstance(obj, str):
        return redact_text(obj, max_len=4000)
    return obj


def fingerprint_payload(payload: Dict[str, Any]) -> str:
    try:
        normalized = json.dumps(redact_payload(payload), sort_keys=True, default=str)
    except (TypeError, ValueError):
        normalized = str(redact_payload(payload))
    return hashlib.sha256(normalized.encode("utf-8", errors="replace")).hexdigest()


def infer_tool_audit_meta(
    evolution_engine: Any,
    tool_name: str,
    *,
    override_backend: Optional[str] = None,
) -> Dict[str, Any]:
    """根据 ``ToolContractRegistry`` 推断工具审计维度（多 MCP 后端并存）。

    与 OpenTelemetry GenAI / MCP 工具观测常见字段的对应关系（AdamI 侧命名）：
    - ``tool_id``：契约层 tool_id（大写），语义接近 span 上的 ``gen_ai.tool.name`` / function name。
    - ``tool_backend``：``native`` | ``mcp_docker`` | ``mcp_agent`` — 执行路径（mcp-agent 文档中的 session/aggregator 对应 ``mcp_agent``）。
    - ``latency_ms``：由调用方测量后写入 ``record_tool_call``，对应 span duration。
    - ``docker_used``：当前 AdamI MCP 传输均为 Docker stdio（含 mcp-agent 映射），便于运营区分「无容器」原生技能。
    - ``mcp_allow_deny``：已注册并可达的 MCP 工具视为通过 allowlist 注册阶段；未走 MCP 则为 ``n/a``。
    """
    tid = str(tool_name or "").upper().strip() or "UNKNOWN"
    meta: Dict[str, Any] = {
        "tool_id": tid,
        "tool_backend": "native",
        "docker_used": False,
        "mcp_allow_deny": "n/a",
    }
    if override_backend:
        meta["tool_backend"] = override_backend
        if override_backend in ("mcp_agent", "mcp_docker"):
            meta["docker_used"] = True
            meta["mcp_allow_deny"] = "allowlist_registered"
        return meta
    reg = getattr(evolution_engine, "tool_contract_registry", None)
    if reg is None:
        return meta
    cap = reg.get(tid)
    if cap is None:
        return meta
    src = getattr(cap, "source", None)
    if src == "mcp":
        meta["tool_backend"] = "mcp_docker"
        meta["docker_used"] = True
        meta["mcp_allow_deny"] = "allowlist_registered"
    return meta


# ---------------------------------------------------------------------------
# Sink
# ---------------------------------------------------------------------------
class ExperienceSink:
    def __init__(
        self,
        *,
        enabled: bool,
        aggregator: ExperienceAggregator,
    ) -> None:
        self._enabled = enabled
        self._aggregator = aggregator
        self._lock = threading.Lock()
        self._ctx_stack: List[tuple[Token, Token]] = []

    @classmethod
    def from_settings(cls) -> ExperienceSink:
        en = bool(getattr(settings, "ADAMI_EXPERIENCE_ENABLED", False))
        base = settings.resolved_experience_dir
        agg = ExperienceAggregator(base)
        return cls(enabled=en, aggregator=agg)

    def begin_episode(
        self,
        episode_id: str,
        primary_trace_id: str,
        *,
        push_context: bool = True,
        **meta: Any,
    ) -> None:
        if not self._enabled:
            return
        m = dict(meta)
        src = m.pop("source", "unknown")
        self._aggregator.ensure_episode(episode_id, primary_trace_id, meta={"source": src, **m})
        if not push_context:
            return
        tok_e = experience_episode_id_ctx.set(episode_id)
        tok_p = experience_primary_trace_ctx.set(primary_trace_id)
        with self._lock:
            self._ctx_stack.append((tok_e, tok_p))

    def end_episode(
        self,
        episode_id: str,
        status: str,
        *,
        extra_meta: Optional[Dict[str, Any]] = None,
        pop_context: bool = True,
    ) -> None:
        if not self._enabled:
            return
        self._aggregator.finalize_episode(episode_id, status, extra_meta=extra_meta)
        if not pop_context:
            return
        with self._lock:
            if not self._ctx_stack:
                return
            tok_e, tok_p = self._ctx_stack.pop()
        experience_episode_id_ctx.reset(tok_e)
        experience_primary_trace_ctx.reset(tok_p)

    def active_episode_id(self) -> Optional[str]:
        return experience_episode_id_ctx.get()

    def _resolve_episode(self, episode_id: Optional[str], trace_id: str) -> str:
        return episode_id or experience_episode_id_ctx.get() or trace_id

    def record_llm_turn(
        self,
        *,
        trace_id: str,
        episode_id: Optional[str] = None,
        brain_type: str,
        provider: str,
        model: str,
        prompt_summary: str,
        completion_summary: str,
        latency_ms: float,
        ok: bool,
        error: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self._enabled:
            return
        eid = self._resolve_episode(episode_id, trace_id)
        payload = redact_payload(
            {
                "brain_type": brain_type,
                "provider": provider,
                "model": model,
                "prompt_summary": prompt_summary,
                "completion_summary": completion_summary,
                "latency_ms": round(latency_ms, 3),
                "ok": ok,
                "error": redact_text(error or "", max_len=500) if error else None,
                **(extra or {}),
            }
        )
        rec = ExperienceRecord(
            trace_id=trace_id,
            episode_id=eid,
            type="llm_turn",
            payload=payload,
            payload_sha256=fingerprint_payload(payload),
        )
        self._aggregator.add_event(eid, rec.model_dump())

    def record_tool_call(
        self,
        *,
        trace_id: str,
        episode_id: Optional[str] = None,
        tool_name: str,
        args_summary: str,
        result_summary: str,
        error_code: Optional[str] = None,
        ok: bool = True,
        tool_id: Optional[str] = None,
        tool_backend: Optional[str] = None,
        latency_ms: Optional[float] = None,
        docker_used: Optional[bool] = None,
        mcp_allow_deny: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self._enabled:
            return
        eid = self._resolve_episode(episode_id, trace_id)
        tid = (tool_id or tool_name or "").strip().upper() or str(tool_name)
        core: Dict[str, Any] = {
            "tool_name": tool_name,
            "tool_id": tid,
            "args_summary": args_summary,
            "result_summary": result_summary,
            "error_code": error_code,
            "ok": ok,
        }
        if tool_backend is not None:
            core["tool_backend"] = tool_backend
        if latency_ms is not None:
            core["latency_ms"] = round(float(latency_ms), 3)
        if docker_used is not None:
            core["docker_used"] = bool(docker_used)
        if mcp_allow_deny is not None:
            core["mcp_allow_deny"] = mcp_allow_deny
        payload = redact_payload({**core, **(extra or {})})
        rec = ExperienceRecord(
            trace_id=trace_id,
            episode_id=eid,
            type="tool_call",
            payload=payload,
            payload_sha256=fingerprint_payload(payload),
        )
        self._aggregator.add_event(eid, rec.model_dump())

    def record_phase_transition(
        self,
        *,
        trace_id: str,
        episode_id: Optional[str] = None,
        from_phase: Optional[str],
        to_phase: str,
        checkpoint_seq: Optional[int] = None,
        gate_detail: str = "",
        source_module: str = "",
        reason: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """模块四：与 Sim NDJSON 对齐的阶段边界事件（经验池侧可聚合阶段数 / checkpoint 数）。"""
        if not self._enabled:
            return
        eid = self._resolve_episode(episode_id, trace_id)
        payload = redact_payload(
            {
                "from_phase": from_phase,
                "to_phase": to_phase,
                "gate_detail": gate_detail,
                "source_module": source_module,
                "reason": redact_text(reason or "", max_len=800),
                **(extra or {}),
            }
        )
        rec = ExperienceRecord(
            trace_id=trace_id,
            episode_id=eid,
            type="phase_transition",
            phase=to_phase,
            checkpoint_seq=checkpoint_seq,
            payload=payload,
            payload_sha256=fingerprint_payload(payload),
        )
        self._aggregator.add_event(eid, rec.model_dump())

    def record_feedback(
        self,
        *,
        trace_id: str,
        episode_id: Optional[str] = None,
        reward: float,
        metadata: Optional[Dict[str, Any]] = None,
        source: str = "unknown",
    ) -> None:
        if not self._enabled:
            return
        eid = self._resolve_episode(episode_id, trace_id)
        payload = redact_payload(
            {
                "reward": reward,
                "metadata": metadata or {},
                "source": source,
            }
        )
        rec = ExperienceRecord(
            trace_id=trace_id,
            episode_id=eid,
            type="feedback",
            payload=payload,
            payload_sha256=fingerprint_payload(payload),
        )
        self._aggregator.add_event(eid, rec.model_dump())


_experience_sink_instance: Optional[ExperienceSink] = None
_sink_lock = threading.Lock()


def get_experience_sink() -> ExperienceSink:
    global _experience_sink_instance
    if _experience_sink_instance is not None:
        return _experience_sink_instance
    with _sink_lock:
        if _experience_sink_instance is None:
            if getattr(settings, "ADAMI_EXPERIENCE_ENABLED", False):
                _experience_sink_instance = ExperienceSink.from_settings()
            else:
                _experience_sink_instance = ExperienceSink(
                    enabled=False,
                    aggregator=ExperienceAggregator(Path(".")),
                )
        return _experience_sink_instance


def reset_experience_sink_for_tests() -> None:
    """测试专用：清空单例。"""
    global _experience_sink_instance
    with _sink_lock:
        _experience_sink_instance = None
