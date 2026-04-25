"""Pilot: run TaskPlanner branch via mcp-agent Orchestrator + AdamI MCP server specs (Docker stdio).

Requires: ``poetry install -E mcp-agent`` (or equivalent) and non-empty ``ADAMI_MCP_SERVERS_JSON``.
See ``docs/mcp_agent_alignment.md`` and https://docs.mcp-agent.com/mcp-agent-sdk/effective-patterns/planner.md
"""

from __future__ import annotations

import logging
from typing import Optional

import adami_kernel.config as config_mod
from adami_kernel.integration.mcp_agent.mcp_agent_config import (
    build_mcp_app_settings,
    build_mcpserver_settings_map,
)
from adami_kernel.mcp.config_loader import load_mcp_server_specs

logger = logging.getLogger("AdamI-MCPAgentPlanner")


async def try_mcp_agent_planner(task: str, brain_preamble: str = "") -> Optional[str]:
    """If enabled and dependencies OK, run mcp-agent orchestrator; else return ``None``."""
    if not config_mod.mcp_agent_planner_pilot_effective(config_mod.settings):
        return None

    try:
        from mcp_agent.agents.agent_spec import AgentSpec  # type: ignore[import-untyped]
        from mcp_agent.app import MCPApp  # type: ignore[import-untyped]
        from mcp_agent.workflows.factory import create_orchestrator  # type: ignore[import-untyped]
        from mcp_agent.workflows.orchestrator.orchestrator import (  # type: ignore[import-untyped]
            OrchestratorOverrides,
        )
    except ImportError:
        logger.debug("[MCPAgent] mcp-agent package not installed; skip pilot")
        return None

    specs = load_mcp_server_specs()
    if not specs:
        logger.info("[MCPAgent] ADAMI_MCP_SERVERS_JSON empty; skip pilot")
        return None

    servers = build_mcpserver_settings_map()
    if not servers:
        logger.warning("[MCPAgent] no valid MCP servers after Docker mapping; skip pilot")
        return None

    try:
        provider, mcp_settings = build_mcp_app_settings(
            servers,
            app_name="adami_kernel_planner_mcp_agent",
        )
    except Exception as e:
        logger.warning("[MCPAgent] settings build failed: %s", e)
        return None

    plan_type = getattr(config_mod.settings, "ADAMI_MCP_AGENT_PLAN_TYPE", "iterative")
    if plan_type not in ("full", "iterative"):
        plan_type = "iterative"

    server_names = list(servers.keys())
    objective = f"{brain_preamble}\n\n任务：\n{task}".strip()

    app = MCPApp(settings=mcp_settings)
    try:
        async with app.run() as running_app:
            orchestrator = create_orchestrator(  # type: ignore[unknown-variable-type]
                available_agents=[
                    AgentSpec(
                        name="mcp_worker",
                        instruction=(
                            "You can call MCP tools from the configured servers. "
                            "Use them to answer the task; be concise and factual."
                        ),
                        server_names=server_names,
                    ),
                ],
                plan_type=plan_type,  # type: ignore[arg-type]
                provider=provider,
                model=config_mod.settings.ADAMI_THINK_MODEL,
                overrides=OrchestratorOverrides(
                    planner_instruction=(
                        "Break the goal into a small number of steps and assign them to the worker. "
                        "Prefer tool use when it helps."
                    ),
                    synthesizer_instruction=(
                        "Produce the final user-facing answer. "
                        "Match the user's language (e.g. Chinese if the task is in Chinese)."
                    ),
                ),
                context=running_app.context,
                name="adami_planner_pilot",
            )
            text = await orchestrator.generate_str(objective)  # type: ignore[unknown-member-type]
            return text
    except Exception as e:
        logger.warning("[MCPAgent] orchestrator run failed: %s", e, exc_info=True)
        return None
