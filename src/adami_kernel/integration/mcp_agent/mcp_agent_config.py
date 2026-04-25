"""Shared mcp-agent Settings + Docker stdio mapping from ``ADAMI_MCP_SERVERS_JSON`` (3.1: allowlist + read-only)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

import adami_kernel.config as config_mod
from adami_kernel.mcp.config_loader import load_mcp_server_specs
from adami_kernel.mcp.spec import McpServerSpec

logger = logging.getLogger("AdamI-MCPAgentConfig")

SupportedProvider = Literal["openai", "anthropic", "google", "azure", "ollama", "bedrock"]


def docker_run_args_for_mcp_spec(spec: McpServerSpec) -> List[str]:
    """Build ``docker run ...`` argv (excluding leading ``docker``) matching ``McpDockerStdioRunner``."""
    inner: List[str] = []
    if spec.command:
        inner.extend(spec.command)
    if spec.args:
        inner.extend(spec.args)
    if not inner:
        raise ValueError(f"MCP server {spec.name!r} has empty command/args")

    network_mode = config_mod.settings.ADAMI_MCP_DOCKER_NETWORK_MODE
    read_only = (
        bool(spec.read_only_fs)
        if spec.read_only_fs is not None
        else bool(getattr(config_mod.settings, "ADAMI_MCP_READ_ONLY_FS", True))
    )

    run_args: List[str] = ["run", "-i", "--rm", f"--network={network_mode}"]
    if read_only:
        run_args.append("--read-only")
        run_args.extend(["--tmpfs", "/tmp:rw,noexec,nosuid,size=64m"])  # noqa: S108
    run_args.extend(["--security-opt", "no-new-privileges:true"])
    run_args.extend(["-m", "512m"])
    run_args.extend(["--cpus", "0.5"])

    workdir = spec.workdir or "/"
    run_args.extend(["-w", workdir])

    allowlist = [
        str(x) for x in (config_mod.settings.ADAMI_MCP_MOUNT_ALLOWLIST or []) if str(x).strip()
    ]
    for m in spec.mounts or []:
        src = str(Path(m.source).expanduser().resolve())
        if not allowlist:
            raise RuntimeError(
                f"[MCPAgent] mount declared but ADAMI_MCP_MOUNT_ALLOWLIST is empty: {src}"
            )
        if not any(src.startswith(str(Path(p).expanduser().resolve())) for p in allowlist):
            raise RuntimeError(f"[MCPAgent] mount source not allowed: {src}")
        run_args.extend(["-v", f"{src}:{m.target}:{m.mode}"])

    container_env = {
        "PYTHONUNBUFFERED": "1",
        "ADAMI_SANDBOX_MODE": "true",
        "OPENAI_API_KEY": "sk-dummy-key-for-testing-only",
        "KIMI_API_KEY": "sk-dummy-key-for-testing-only",
        "ANTHROPIC_API_KEY": "sk-dummy-key-for-testing-only",
        "DEEPSEEK_API_KEY": "sk-dummy-key-for-testing-only",
        **(spec.env or {}),
    }
    for k, v in container_env.items():
        run_args.extend(["-e", f"{k}={v}"])

    run_args.append(spec.image)
    run_args.extend(inner)
    return run_args


def _has(val: Optional[str]) -> bool:
    return bool(val and str(val).strip())


def pick_llm_provider() -> Optional[SupportedProvider]:
    s = config_mod.settings
    raw = (getattr(s, "ADAMI_MCP_AGENT_LLM_PROVIDER", None) or "").strip().lower()
    allowed: Tuple[SupportedProvider, ...] = (
        "openai",
        "anthropic",
        "google",
        "azure",
        "ollama",
        "bedrock",
    )
    if raw:
        if raw not in allowed:
            logger.warning("[MCPAgent] invalid ADAMI_MCP_AGENT_LLM_PROVIDER=%r", raw)
            return None
        return raw  # type: ignore[return-value]
    if _has(s.OPENAI_API_KEY):
        return "openai"
    if _has(s.GEMINI_API_KEY):
        return "google"
    if _has(s.ANTHROPIC_API_KEY):
        return "anthropic"
    return None


def build_mcpserver_settings_map() -> Dict[str, Any]:
    """Return ``{server_name: MCPServerSettings}`` for mcp-agent (Docker stdio only)."""
    from mcp_agent.config import MCPServerSettings  # type: ignore[import-untyped]

    specs = load_mcp_server_specs()
    servers: Dict[str, MCPServerSettings] = {}
    for spec in specs:
        try:
            args = docker_run_args_for_mcp_spec(spec)
        except (RuntimeError, ValueError) as e:
            logger.warning("[MCPAgent] skip server %s: %s", spec.name, e)
            continue
        servers[spec.name] = MCPServerSettings(command="docker", args=args)
    return servers


def build_mcp_app_settings(
    servers: Dict[str, Any],
    *,
    app_name: str = "adami_kernel_mcp_agent",
) -> Tuple[SupportedProvider, Any]:
    """Build mcp-agent ``Settings`` for given MCP server map (provider from AdamI keys)."""
    from mcp_agent.config import (  # type: ignore[import-untyped]
        AnthropicSettings,
        GoogleSettings,
        LoggerSettings,
        MCPSettings,
        OpenAISettings,
        Settings,
        UsageTelemetrySettings,
    )

    provider = pick_llm_provider()
    if provider is None:
        raise RuntimeError(
            "No LLM provider for mcp-agent: set OPENAI_API_KEY, GEMINI_API_KEY, "
            "ANTHROPIC_API_KEY, or ADAMI_MCP_AGENT_LLM_PROVIDER with matching credentials"
        )

    s = config_mod.settings
    if provider in ("azure", "ollama", "bedrock"):
        raise RuntimeError(
            f"ADAMI_MCP_AGENT_LLM_PROVIDER={provider!r} is not implemented in the AdamI adapter; "
            "use openai, google, or anthropic."
        )
    kwargs: Dict[str, Any] = {
        "name": app_name,
        "execution_engine": "asyncio",
        "logger": LoggerSettings(
            transports=["console"],
            level="warning",
            progress_display=False,
        ),
        "mcp": MCPSettings(servers=servers),
        "usage_telemetry": UsageTelemetrySettings(enabled=False),
    }

    if provider == "openai":
        if not _has(s.OPENAI_API_KEY):
            raise RuntimeError("OPENAI_API_KEY required for mcp-agent openai provider")
        kwargs["openai"] = OpenAISettings(
            api_key=s.OPENAI_API_KEY or "",
            base_url=s.LLM_BASE_URL or None,
            default_model=s.ADAMI_THINK_MODEL,
        )
    elif provider == "google":
        if not _has(s.GEMINI_API_KEY):
            raise RuntimeError("GEMINI_API_KEY required for mcp-agent google provider")
        kwargs["google"] = GoogleSettings(
            api_key=s.GEMINI_API_KEY or "",
            default_model=s.ADAMI_THINK_MODEL,
            vertexai=False,
        )
    elif provider == "anthropic":
        if not _has(s.ANTHROPIC_API_KEY):
            raise RuntimeError("ANTHROPIC_API_KEY required for mcp-agent anthropic provider")
        kwargs["anthropic"] = AnthropicSettings(
            api_key=s.ANTHROPIC_API_KEY or "",
            default_model=s.ADAMI_THINK_MODEL,
        )
    else:
        raise RuntimeError(f"Unsupported provider {provider!r}")

    return provider, Settings(**kwargs)
