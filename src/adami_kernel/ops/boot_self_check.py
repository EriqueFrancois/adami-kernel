"""
启动前自检（运维）：汇总当前启用的功能模块，并标出高风险配置组合。

只读 ``Settings`` / 环境，不启动 EventBus、不连外网（除可选 Docker ping 探测）。
"""

from __future__ import annotations

import urllib.parse
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, List, Optional

from adami_kernel.config import (
    Settings,
    markitdown_effective_enabled,
    mcp_agent_module_master_enabled,
    mcp_agent_planner_pilot_effective,
    mcp_agent_tool_execution_effective,
    sim_module_master_enabled,
)
from adami_kernel.nexus.nerve_registry import validate_messenger_routing_for_ops_check


def _docker_daemon_reachable() -> Optional[bool]:
    try:
        import docker

        return bool(docker.from_env().ping())  # type: ignore[reportUnknownMemberType]
    except Exception:
        return None


def _nerve_preflight_warnings() -> List[str]:
    out: List[str] = []
    try:
        validate_messenger_routing_for_ops_check()
    except RuntimeError as e:
        out.append(f"[BLOCKER] Nerve registration would fail: {e}")
    except Exception as e:  # pragma: no cover
        out.append(f"[WARN] Messenger routing preflight raised unexpectedly: {e}")
    return out


def _deerflow_base_host_is_localish(url: Optional[str]) -> bool:
    if not url or not str(url).strip():
        return False
    try:
        p = urllib.parse.urlparse(str(url).strip())
        host = (p.hostname or "").lower()
        return host in ("localhost", "127.0.0.1", "::1")
    except Exception:
        return False


def _empty_str_list() -> list[str]:
    return []


@dataclass
class BootSelfCheckReport:
    """Structured report for humans and ``--json``."""

    runtime_profile: str
    in_container_auto: bool
    debug: bool
    docker_daemon_reachable: Optional[bool]
    modules_enabled: List[str] = field(default_factory=_empty_str_list)
    modules_notable_off: List[str] = field(default_factory=_empty_str_list)
    warnings: List[str] = field(default_factory=_empty_str_list)

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


def collect_enabled_modules(s: Settings) -> tuple[list[str], list[str]]:
    """Returns (enabled lines, short list of notable disabled flags for ops context)."""
    on: list[str] = []
    off: list[str] = []

    def _add_on(label: str) -> None:
        on.append(label)

    def _add_off(label: str) -> None:
        off.append(label)

    if s.ADAMI_USE_WORKFLOW_ENGINE:
        _add_on("WorkflowEngine")
    else:
        _add_off("WorkflowEngine")

    if s.ADAMI_USE_MULTI_AGENT:
        _add_on("Multi-agent orchestration")
    else:
        _add_off("Multi-agent")

    if s.ADAMI_USE_REFLEXION_LOOP:
        _add_on("Reflexion loop")
    if s.ADAMI_USE_TDD_EVOLUTION:
        _add_on("TDD evolution")

    if s.ADAMI_ENABLE_OBSERVABILITY:
        _add_on(f"Observability (OTEL exporter={s.ADAMI_OTEL_EXPORTER})")
    if s.ADAMI_ENABLE_HITL:
        _add_on("HITL (human-in-the-loop)")
    if s.ADAMI_ENABLE_MULTI_TENANT:
        _add_on("Multi-tenant (experimental)")

    if s.ADAMI_MCP_ENABLED:
        _add_on("MCP stdio servers (ADAMI_MCP_ENABLED)")
    else:
        _add_off("MCP stdio servers")

    if mcp_agent_module_master_enabled(s):
        bits: list[str] = []
        if mcp_agent_tool_execution_effective(s):
            bits.append("tool execution")
        if mcp_agent_planner_pilot_effective(s):
            bits.append("planner pilot")
        if bits:
            _add_on("MCP-Agent module: " + ", ".join(bits))
        else:
            _add_on("MCP-Agent module (master on; execution/planner off)")
    else:
        _add_off("MCP-Agent module")

    if sim_module_master_enabled(s):
        _add_on("Sim / replay module (master)")
        if s.ADAMI_SIM_TRACE_EXPORT_ENABLED:
            _add_on("Sim trace NDJSON export")
        if s.ADAMI_SIM_WEBHOOK_ENABLED:
            _add_on("Sim webhook bridge")
    else:
        _add_off("Sim module")

    if s.ADAMI_LONG_TASK_TRACKING_ENABLED:
        _add_on("Long-task tracking (DeerFlow-style phases)")
    if s.ADAMI_DEERFLOW_ENABLED:
        _add_on("DeerFlow sidecar bridge")

    if s.ADAMI_LAST30DAYS_ENABLED:
        _add_on("last30days external CLI sensor")

    if s.ADAMI_INTENT_ADAPTIVE_PIPELINE_ENABLED:
        _add_on("Intent adaptive pipeline (pre-Planner)")
    if s.ADAMI_INTENT_LLM_CLASSIFIER_ENABLED:
        _add_on("Intent LLM classifier")

    if markitdown_effective_enabled(s):
        _add_on("MarkItDown document path (effective)")
    if s.ADAMI_TRANSLATE_ENABLED:
        _add_on("Explicit translate module (i18n)")

    if str(getattr(s, "TELEGRAM_BOT_TOKEN", "") or "").strip():
        _add_on("Telegram nerve (token present)")
    if str(getattr(s, "DISCORD_BOT_TOKEN", "") or "").strip():
        _add_on("Discord nerve (token present)")

    if s.ADAMI_ENABLE_SELF_TEST:
        _add_on("Self-test engine")
    if s.ADAMI_AUTO_EVOLUTION_ENABLED:
        _add_on("Auto-evolution (MetaCortex)")
    if s.ADAMI_EXPERIENCE_ENABLED:
        _add_on("Experience / policy hot-reload stack")
    if s.ADAMI_AGL_ENABLED:
        _add_on("Agent Lightning compat sink (ADAMI_AGL_ENABLED)")
    if s.ADAMI_TRAIN_SCHEDULE_ENABLED:
        _add_on("Wall-clock training schedule")
    if s.ADAMI_IDLE_TRAIN_ENABLED:
        _add_on("Idle-gated training")

    if not s.ADAMI_SKIP_DOCKER_SANDBOX:
        _add_on("DreamSandbox: Docker path preferred (ADAMI_SKIP_DOCKER_SANDBOX=false)")
    else:
        _add_off("Docker skill sandbox (skipped → host fallback where used)")

    return on, off


def collect_warnings(s: Settings, *, docker_reachable: Optional[bool]) -> List[str]:
    w: List[str] = []

    profile = str(getattr(s, "ADAMI_RUNTIME_PROFILE", "") or "unknown")
    if profile == "production" and s.DEBUG:
        w.append(
            "[WARN] ADAMI_RUNTIME_PROFILE=production but DEBUG=true — avoid in real deployments."
        )

    if profile == "production" and str(s.ADAMI_MCP_DOCKER_NETWORK_MODE or "").lower() == "host":
        w.append(
            "[WARN] MCP Docker network_mode=host weakens isolation under production profile; prefer bridge."
        )

    if not s.ADAMI_SKIP_DOCKER_SANDBOX:
        if docker_reachable is False:
            w.append(
                "[WARN] ADAMI_SKIP_DOCKER_SANDBOX=false but Docker daemon did not respond to ping — "
                "skill sandbox/inspector may fall back to host execution."
            )
        elif docker_reachable is None:
            w.append(
                "[INFO] Docker reachability unknown (docker SDK missing or error); "
                "verify manually if ADAMI_SKIP_DOCKER_SANDBOX=false."
            )

    if s.ADAMI_MCP_ENABLED:
        allow = list(getattr(s, "ADAMI_MCP_ALLOW_TOOLS", []) or [])
        deny = list(getattr(s, "ADAMI_MCP_DENY_TOOLS", []) or [])
        if not allow and not deny:
            w.append(
                "[WARN] MCP enabled with empty ADAMI_MCP_ALLOW_TOOLS and ADAMI_MCP_DENY_TOOLS — "
                "review tool exposure vs your threat model."
            )

    if s.ADAMI_SIM_WEBHOOK_ENABLED:
        if not str(getattr(s, "ADAMI_SIM_WEBHOOK_SECRET", "") or "").strip():
            w.append(
                "[WARN] Sim webhook enabled but ADAMI_SIM_WEBHOOK_SECRET is empty — weak authenticity."
            )

    if s.ADAMI_INTENT_ADAPTIVE_PIPELINE_ENABLED and s.ADAMI_INTENT_ACTION_PERMISSION_GRANTED:
        w.append(
            "[WARN] Intent adaptive pipeline + ADAMI_INTENT_ACTION_PERMISSION_GRANTED — "
            "ACTION family may stay primary in merges; confirm this matches your safety bar."
        )

    if s.ADAMI_DEERFLOW_ENABLED:
        base = getattr(s, "ADAMI_DEERFLOW_BASE_URL", None)
        u = str(base or "").strip()
        if u and u.lower().startswith("http://") and not _deerflow_base_host_is_localish(u):
            w.append(
                "[WARN] DeerFlow ADAMI_DEERFLOW_BASE_URL uses cleartext HTTP on a non-loopback host — "
                "prefer HTTPS or TLS client config for production."
            )
        if (
            not s.ADAMI_DEERFLOW_REQUIRE_TOKEN
            and str(getattr(s, "ADAMI_DEERFLOW_TOKEN", "") or "").strip() == ""
        ):
            w.append(
                "[INFO] DeerFlow enabled with ADAMI_DEERFLOW_REQUIRE_TOKEN=false and no token — "
                "ensure the sidecar is network-isolated as intended."
            )

    if s.ADAMI_ENABLE_MULTI_TENANT:
        w.append(
            "[WARN] ADAMI_ENABLE_MULTI_TENANT=true — treat as experimental; review isolation guarantees."
        )

    w.extend(_nerve_preflight_warnings())
    return w


def run_boot_self_check(s: Optional[Settings] = None) -> BootSelfCheckReport:
    """Build a full report using current ``Settings`` (or an injected instance for tests)."""
    s = s if s is not None else __import__("adami_kernel.config", fromlist=["settings"]).settings
    assert isinstance(s, Settings)

    in_container = Path("/.dockerenv").is_file()
    profile = str(getattr(s, "ADAMI_RUNTIME_PROFILE", "") or "unknown")
    dkr = _docker_daemon_reachable()
    on, off = collect_enabled_modules(s)
    warns = collect_warnings(s, docker_reachable=dkr)

    return BootSelfCheckReport(
        runtime_profile=profile,
        in_container_auto=in_container,
        debug=bool(s.DEBUG),
        docker_daemon_reachable=dkr,
        modules_enabled=on,
        modules_notable_off=off[:24],
        warnings=warns,
    )
