"""Unit tests for mcp-agent planner pilot helpers (no Docker / no live LLM)."""

from __future__ import annotations

import pytest

from adami_kernel.integration.mcp_agent.mcp_agent_config import docker_run_args_for_mcp_spec
from adami_kernel.mcp.spec import McpMountSpec, McpServerSpec


def test_docker_run_args_minimal() -> None:
    spec = McpServerSpec(
        name="demo",
        image="alpine:3.20",
        command=["echo"],
        args=["hi"],
    )
    argv = docker_run_args_for_mcp_spec(spec)
    assert argv[0:3] == ["run", "-i", "--rm"]
    assert any(a.startswith("--network=") for a in argv)
    assert argv[-3:] == ["alpine:3.20", "echo", "hi"]
    assert "-e" in argv
    assert any(x.startswith("PYTHONUNBUFFERED=") for x in argv if "=" in x)


def test_docker_run_args_mount_requires_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "adami_kernel.integration.mcp_agent.mcp_agent_config.config_mod.settings.ADAMI_MCP_MOUNT_ALLOWLIST",
        [],
    )
    spec = McpServerSpec(
        name="m",
        image="img",
        command=["x"],
        args=[],
        mounts=[McpMountSpec(source="/tmp", target="/data", mode="ro")],  # noqa: S108
    )
    with pytest.raises(RuntimeError, match="ALLOWLIST"):
        docker_run_args_for_mcp_spec(spec)


@pytest.mark.asyncio
async def test_try_mcp_agent_planner_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "adami_kernel.integration.mcp_agent.planner_bridge.config_mod.settings.ADAMI_USE_MCP_AGENT_PLANNER",
        False,
    )
    from adami_kernel.integration.mcp_agent.planner_bridge import try_mcp_agent_planner

    assert await try_mcp_agent_planner("hello", "") is None


@pytest.mark.asyncio
async def test_try_mcp_agent_planner_master_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "adami_kernel.integration.mcp_agent.planner_bridge.config_mod.settings.ADAMI_MCP_MODULE_AGENT_ENABLED",
        False,
    )
    monkeypatch.setattr(
        "adami_kernel.integration.mcp_agent.planner_bridge.config_mod.settings.ADAMI_USE_MCP_AGENT_PLANNER",
        True,
    )
    from adami_kernel.integration.mcp_agent.planner_bridge import try_mcp_agent_planner

    assert await try_mcp_agent_planner("hello", "") is None
