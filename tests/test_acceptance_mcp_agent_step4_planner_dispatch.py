"""验收：步骤 4（TaskPlanner 工具执行：契约层 + ADAMI_USE_MCP_AGENT 试点）。

验收方案（自动项在本文件；端到端 Docker/MCP/LLM 见 docstring 末）
----------------------------------------------------------------
**步骤 4**
- AC-4.1 ``config.py`` 定义 ``ADAMI_USE_MCP_AGENT``（bool），与 ``ADAMI_USE_MCP_AGENT_PLANNER`` 独立并存。
- AC-4.2 新建 ``integration/mcp_agent/tool_executor.py``，导出 ``try_execute_via_mcp_agent``、``mcp_agent_tool_execution_enabled``。
- AC-4.3 ``EvolutionEngine`` 实现 ``execute_tool_dispatch``、``execute_with_retry``（Planner 规划步骤历史入口补齐）。
- AC-4.4 ``planner.py`` 在 SkillRouter / 关键词 / 规划循环中调用 ``execute_tool_dispatch`` 或 ``execute_with_retry``，并传入 ``trace_id`` / ``chat_id``。
- AC-4.5 ``.env.example`` 提示 ``ADAMI_USE_MCP_AGENT``。
- AC-4.6 子进程验证：仅设置 ``ADAMI_USE_MCP_AGENT=1`` 时，``adami_kernel.config.settings`` 为真（与 pydantic-settings 一致）。
- AC-4.7 ``tool_executor`` 在试点关闭时对非 MCP 契约立即返回 ``None``（不拉起 MCPApp）。

**与 ``tests/test_planner_tool_dispatch.py`` 的关系**
- 该文件覆盖：关开关原生路径、开开关 pilot 短路、pilot 返回 ``None`` 回退、``execute_with_retry`` 透传；验收执行时一并跑通。

**建议人工 / CI（本文件不强制执行）**
- 打开 ``ADAMI_USE_MCP_AGENT=1`` + 有效 ``ADAMI_MCP_SERVERS_JSON`` + LLM 密钥：真实 Planner 一轮规划调用 MCP 工具，日志含 ``trace_id``；拔 Docker 或断 MCP 时应 warning 且任务仍可经 Docker 回退完成（视环境）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC_CONFIG = ROOT / "src" / "adami_kernel" / "config.py"
SRC_EVOLUTION = ROOT / "src" / "adami_kernel" / "cortex" / "evolution.py"
SRC_PLANNER = ROOT / "src" / "adami_kernel" / "orchestrator" / "planner.py"
SRC_TOOL_EXEC = ROOT / "src" / "adami_kernel" / "integration" / "mcp_agent" / "tool_executor.py"
ENV_EXAMPLE = ROOT / ".env.example"


def test_ac_4_1_config_defines_use_mcp_agent_independent_of_planner_flag() -> None:
    text = SRC_CONFIG.read_text(encoding="utf-8")
    assert "ADAMI_MCP_MODULE_AGENT_ENABLED: bool = True" in text
    assert "ADAMI_USE_MCP_AGENT_PLANNER: bool = True" in text
    assert "ADAMI_USE_MCP_AGENT: bool = True" in text
    assert "def mcp_agent_tool_execution_effective" in text
    assert "def mcp_agent_planner_pilot_effective" in text


def test_ac_4_2_tool_executor_module_present() -> None:
    assert SRC_TOOL_EXEC.is_file()
    body = SRC_TOOL_EXEC.read_text(encoding="utf-8")
    assert "def try_execute_via_mcp_agent" in body
    assert "def mcp_agent_tool_execution_enabled" in body


def test_ac_4_3_evolution_engine_has_dispatch_and_retry() -> None:
    body = SRC_EVOLUTION.read_text(encoding="utf-8")
    assert "async def execute_tool_dispatch" in body
    assert "async def execute_with_retry" in body
    assert "ToolInvocation" in body


def test_ac_4_4_planner_passes_trace_and_uses_dispatch() -> None:
    body = SRC_PLANNER.read_text(encoding="utf-8")
    assert "execute_tool_dispatch" in body
    assert "execute_with_retry" in body
    assert "trace_id=trace_id" in body
    assert "chat_id=chat_id" in body


def test_ac_4_5_env_example_mentions_switch() -> None:
    assert ENV_EXAMPLE.is_file()
    assert "ADAMI_USE_MCP_AGENT" in ENV_EXAMPLE.read_text(encoding="utf-8")


def test_ac_4_6_subprocess_env_one_enables_settings() -> None:
    src = str(ROOT / "src")
    prev = os.environ.get("PYTHONPATH", "")
    env = {
        **os.environ,
        "ADAMI_USE_MCP_AGENT": "1",
        "PYTHONPATH": f"{src}{os.pathsep}{prev}" if prev else src,
    }
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import adami_kernel.config as c; print('1' if c.settings.ADAMI_USE_MCP_AGENT else '0')",
        ],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "1"


def test_ac_4_8_master_switch_disables_effective_mcp_agent_paths() -> None:
    from adami_kernel.config import (
        Settings,
        mcp_agent_planner_pilot_effective,
        mcp_agent_tool_execution_effective,
    )

    s = Settings.model_construct(
        ADAMI_MCP_MODULE_AGENT_ENABLED=False,
        ADAMI_USE_MCP_AGENT=True,
        ADAMI_USE_MCP_AGENT_PLANNER=True,
    )
    assert mcp_agent_tool_execution_effective(s) is False
    assert mcp_agent_planner_pilot_effective(s) is False


@pytest.mark.asyncio
async def test_ac_4_7_try_execute_returns_none_when_disabled_for_native_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """试点关 + 契约为 native 时，``try_execute_via_mcp_agent`` 不调 MCPApp。"""
    from adami_kernel.integration.mcp_agent import tool_executor as te
    from adami_kernel.integration.mcp_agent.contracts import (
        ToolCapability,
        ToolInvocation,
    )

    monkeypatch.setattr("adami_kernel.config.settings.ADAMI_USE_MCP_AGENT", False)
    inv = ToolInvocation(tool_id="NATIVE.X", args={}, trace_id="ac4", chat_id="c1")
    cap = ToolCapability(
        tool_id="NATIVE.X",
        source="native",
        json_schema={},
        description="",
    )
    out = await te.try_execute_via_mcp_agent(inv, cap)
    assert out is None
