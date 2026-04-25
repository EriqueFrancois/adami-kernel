"""Adapter smoke helpers (no Docker / no live LLM when mcp-agent optional)."""

from __future__ import annotations

import pytest

pytest.importorskip("mcp_agent")


@pytest.mark.asyncio
async def test_adamimcp_runtime_raises_when_no_servers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "adami_kernel.integration.mcp_agent.adapter.build_mcpserver_settings_map",
        lambda: {},
    )
    from adami_kernel.integration.mcp_agent.adapter import adamimcp_runtime

    with pytest.raises(RuntimeError, match="No MCP servers"):
        async with adamimcp_runtime():
            pass  # pragma: no cover
