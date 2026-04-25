"""验收：步骤 3（mcp-agent 薄适配器 + smoke CLI）。

验收方案（自动项在本文件；需 Docker/密钥的项在 docstring 末）
----------------------------------------------------------------
**步骤 3**
- AC-3.1 工件存在：`integration/mcp_agent/adapter.py`、`adapter_smoke.py`。
- AC-3.2 ``pyproject.toml`` 注册控制台脚本 ``adami-mcp-agent-smoke`` → ``adapter_smoke:main``。
- AC-3.3 适配器通过 ``mcp_agent_config`` 使用 ``build_mcpserver_settings_map`` / ``build_mcp_app_settings``（与 Docker §3.1 映射同源，避免双维护）。
- AC-3.4 关键符号可导入：``adamimcp_runtime``、``run_single_turn_with_agent_llm``、``AdamIRouterAugmentedLLM``、``LLMMode``。
- AC-3.5 若当前环境已安装 ``mcp-agent``：``AdamIRouterAugmentedLLM`` 继承包内真实 ``OpenAIAugmentedLLM``（非占位 stub）。
- AC-3.6 若已安装 ``mcp-agent``：空 server 映射时 ``adamimcp_runtime`` 抛出 ``RuntimeError``（与单元测试一致）。
- AC-3.7 ``adapter_smoke`` 提供 ``if __name__ == '__main__'``，``python -m ...adapter_smoke`` 与 ``adami-mcp-agent-smoke`` 行为一致；
  在 ``ADAMI_MCP_SERVERS_JSON=[]`` 下子进程运行应 **SKIP** 且退出码 **0**。

**建议人工 / CI（本文件不强制执行）**
- 配置有效 ``ADAMI_MCP_SERVERS_JSON``（如 dummy MCP 容器）+ Provider API Key：运行 ``adami-mcp-agent-smoke``，
  确认单次 ``generate_str`` 能列出/调用 MCP tool。
- ``poetry run pyright`` 针对 ``adapter.py`` / ``adapter_smoke.py``（可在 CI 与 ruff/pytest 并列）。
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import get_args

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC_ADAPTER = ROOT / "src" / "adami_kernel" / "integration" / "mcp_agent" / "adapter.py"
SRC_SMOKE = ROOT / "src" / "adami_kernel" / "integration" / "mcp_agent" / "adapter_smoke.py"
PYPROJECT = ROOT / "pyproject.toml"


def _poetry_toml_text() -> str:
    return PYPROJECT.read_text(encoding="utf-8")


def test_ac_3_1_adapter_artifacts_exist() -> None:
    assert SRC_ADAPTER.is_file(), "adapter.py 应存在"
    assert SRC_SMOKE.is_file(), "adapter_smoke.py 应存在"


def test_ac_3_2_poetry_console_script_registered() -> None:
    text = _poetry_toml_text()
    assert "adami-mcp-agent-smoke" in text
    assert "adami_kernel.integration.mcp_agent.adapter_smoke:main" in text


def test_ac_3_3_adapter_uses_mcp_agent_config_for_servers() -> None:
    body = SRC_ADAPTER.read_text(encoding="utf-8")
    assert "build_mcpserver_settings_map" in body
    assert "build_mcp_app_settings" in body
    assert "mcp_agent_config" in body


def test_ac_3_4_public_adapter_api_importable() -> None:
    from adami_kernel.integration.mcp_agent.adapter import (
        AdamIRouterAugmentedLLM,
        LLMMode,
        adamimcp_runtime,
        run_single_turn_with_agent_llm,
    )

    assert callable(adamimcp_runtime)
    assert callable(run_single_turn_with_agent_llm)
    assert AdamIRouterAugmentedLLM is not None
    assert get_args(LLMMode) == ("openai", "router_hybrid")


@pytest.mark.skipif(
    importlib.util.find_spec("mcp_agent") is None,
    reason="mcp-agent extra not installed",
)
def test_ac_3_5_router_llm_subclasses_real_openai_augmented() -> None:
    from mcp_agent.workflows.llm.augmented_llm_openai import OpenAIAugmentedLLM

    from adami_kernel.integration.mcp_agent.adapter import AdamIRouterAugmentedLLM

    assert issubclass(AdamIRouterAugmentedLLM, OpenAIAugmentedLLM)


@pytest.mark.asyncio
@pytest.mark.skipif(
    importlib.util.find_spec("mcp_agent") is None,
    reason="mcp-agent extra not installed",
)
async def test_ac_3_6_empty_servers_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "adami_kernel.integration.mcp_agent.adapter.build_mcpserver_settings_map",
        lambda: {},
    )
    from adami_kernel.integration.mcp_agent.adapter import adamimcp_runtime

    with pytest.raises(RuntimeError, match="No MCP servers"):
        async with adamimcp_runtime():
            pass  # pragma: no cover


@pytest.mark.skipif(
    importlib.util.find_spec("mcp_agent") is None,
    reason="mcp-agent extra not installed",
)
def test_ac_3_7_smoke_cli_skips_when_no_servers() -> None:
    """无 MCP 配置时 CLI 应 SKIP 且退出码 0（不误导 CI 失败）。"""
    src = str(ROOT / "src")
    prev = os.environ.get("PYTHONPATH", "")
    env = {
        **os.environ,
        "ADAMI_MCP_SERVERS_JSON": "[]",
        "PYTHONPATH": f"{src}{os.pathsep}{prev}" if prev else src,
    }
    proc = subprocess.run(
        [sys.executable, "-m", "adami_kernel.integration.mcp_agent.adapter_smoke", "ping"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, f"stderr={proc.stderr!r} stdout={proc.stdout!r}"
    combined = (proc.stderr or "") + (proc.stdout or "")
    assert "SKIP" in combined or "No MCP servers" in combined
