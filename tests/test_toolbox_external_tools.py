from __future__ import annotations

import asyncio

from adami_kernel.cortex.tools_manager import ToolboxManager


def test_toolbox_register_and_execute_external_tool() -> None:
    tb = ToolboxManager(sandbox_dir=".adami_test_sandbox")

    async def ex(text: str) -> dict:
        return {"text": text}

    tb.register_external_tools(
        source="mcp:dummy",
        tools=[
            {"name": "MCP.DUMMY.ECHO", "json_schema": {"type": "object"}, "description": "echo"}
        ],
        executors={"MCP.DUMMY.ECHO": ex},
    )

    assert "MCP.DUMMY.ECHO" in tb.list_tools()

    async def run() -> None:
        out = await tb.execute_tool("mcp.dummy.echo", {"text": "hello"})
        assert out == {"text": "hello"}

    asyncio.run(run())
