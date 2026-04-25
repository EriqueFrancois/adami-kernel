"""Thin mcp-agent adapter: ``MCPApp.run()`` + ``Agent`` + ``attach_llm`` — 不接管 WorkflowEngine / MultiAgent。

- **MCP**：``ADAMI_MCP_SERVERS_JSON`` → Docker stdio（与 ``McpDockerStdioRunner`` 同构，见 ``mcp_agent_config``，§3.1 allowlist）。
- **LLM 默认**：``OpenAIAugmentedLLM``（mcp-agent 完整工具循环，需 provider Settings）。
- **可选 HybridLLMRouter**：``AdamIRouterAugmentedLLM`` — 当当前 agent **可见 MCP tools 为空** 时，用 ``router.call_llm`` 做单轮文本；**有工具时仍走 OpenAI 路径**（因 Router 无 tool_calls 协议）。
"""

# pyright: reportUnknownMemberType=false, reportUnknownLambdaType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportArgumentType=false, reportAttributeAccessIssue=false

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Literal, Optional, Tuple

from adami_kernel.integration.mcp_agent.mcp_agent_config import (
    build_mcp_app_settings,
    build_mcpserver_settings_map,
)

try:
    from mcp_agent.workflows.llm.augmented_llm_openai import (
        OpenAIAugmentedLLM,  # type: ignore[import-untyped]
    )
except ImportError:

    class OpenAIAugmentedLLM:  # type: ignore[no-redef]
        """Placeholder when optional ``mcp-agent`` extra is not installed."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("mcp-agent not installed. Use: poetry install -E mcp-agent")


logger = logging.getLogger("AdamI-MCPAgentAdapter")

LLMMode = Literal["openai", "router_hybrid"]


@asynccontextmanager
async def adamimcp_runtime(
    *,
    app_name: str = "adami_kernel_mcp_adapter",
) -> AsyncIterator[Tuple[Any, list[str]]]:
    """``async with adamimcp_runtime() as (running_app, server_names):``"""
    try:
        from mcp_agent.app import MCPApp  # type: ignore[import-untyped]
    except ImportError as e:
        raise RuntimeError("mcp-agent not installed. Use: poetry install -E mcp-agent") from e

    servers = build_mcpserver_settings_map()
    if not servers:
        raise RuntimeError(
            "No MCP servers after Docker mapping. Set ADAMI_MCP_SERVERS_JSON with at least one server."
        )

    _, settings = build_mcp_app_settings(servers, app_name=app_name)
    app = MCPApp(settings=settings)
    async with app.run() as running_app:
        yield running_app, list(servers.keys())


async def run_single_turn_with_agent_llm(
    prompt: str,
    *,
    instruction: Optional[str] = None,
    llm_mode: LLMMode = "openai",
    router: Any = None,
    brain_type: str = "think",
    request_params: Any = None,
) -> str:
    """在 ``MCPApp.run()`` 内创建 Agent → ``attach_llm`` → ``generate_str(prompt)``。"""
    from mcp_agent.agents.agent import Agent  # type: ignore[import-untyped]
    from mcp_agent.workflows.llm.augmented_llm import RequestParams  # type: ignore[import-untyped]

    instr = instruction or (
        "You are AdamI's MCP adapter agent. Use MCP tools when they help answer the user. "
        "Be concise."
    )

    async with adamimcp_runtime() as (running_app, server_names):
        agent = Agent(
            name="adami_mcp_adapter",
            instruction=instr,
            server_names=server_names,
            context=running_app.context,
        )
        async with agent:
            if llm_mode == "openai":
                llm = await agent.attach_llm(
                    llm_factory=lambda a: OpenAIAugmentedLLM(agent=a),
                )
            else:
                if router is None:
                    raise ValueError(
                        "llm_mode='router_hybrid' requires router=HybridLLMRouter instance"
                    )
                llm = await agent.attach_llm(
                    llm_factory=lambda a: AdamIRouterAugmentedLLM(
                        agent=a, router=router, brain_type=brain_type
                    ),
                )

            rp = request_params or RequestParams(max_iterations=10, maxTokens=2048)
            return await llm.generate_str(prompt, request_params=rp)  # type: ignore[no-any-return]


class AdamIRouterAugmentedLLM(OpenAIAugmentedLLM):
    """OpenAI AugmentedLLM 子类：无可用 MCP tools 时用 ``HybridLLMRouter.call_llm``。"""

    def __init__(self, *args: Any, router: Any, brain_type: str = "think", **kwargs: Any) -> None:
        self._adami_router = router
        self._adami_brain_type = brain_type
        super().__init__(*args, **kwargs)

    async def generate(self, message: Any, request_params: Any = None) -> list[Any]:
        params = self.get_request_params(request_params)
        listed = await self.agent.list_tools(tool_filter=params.tool_filter)
        if listed.tools:
            return await super().generate(message, request_params)

        prompt = self.message_param_str(message) if not isinstance(message, str) else message
        text = await self._adami_router.call_llm(
            prompt,
            brain_type=self._adami_brain_type,
            temperature=params.temperature,
        )
        from openai.types.chat import ChatCompletionMessage

        return [
            ChatCompletionMessage(
                role="assistant",
                content=text,
                refusal=None,
                annotations=None,
            )
        ]

    async def generate_structured(
        self, message: Any, response_model: Any, request_params: Any = None
    ) -> Any:
        return await super().generate_structured(message, response_model, request_params)
