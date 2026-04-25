"""验收：步骤 6（mcp-agent 适配器 smoke 测试矩阵）。

验收方案（自动项在本文件；CI 矩阵见 docstring 末）
----------------------------------------------------------------
**步骤 6**
- AC-6.1 工件存在：``tests/test_mcp_agent_adapter_smoke.py``。
- AC-6.2 模块级 ``pytest.importorskip("mcp_agent")``，保证无 extra 时整文件不收集用例（默认 CI 绿）。
- AC-6.3 覆盖三类场景（源码断言）：``try_execute_via_mcp_agent`` mock、``run_single_turn_with_agent_llm`` mock、
  步骤 4 ``execute_tool_dispatch`` pilot 优先。
- AC-6.4 文件头 docstring 说明「无 mcp-agent / 带 extra」双轨策略。
- AC-6.5 若当前环境已安装 ``mcp-agent``：``pytest --collect-only`` 对该文件收集 **3** 条用例。

**执行验收（本仓库）**
- ``pytest tests/test_acceptance_mcp_agent_step6_smoke_matrix.py tests/test_mcp_agent_adapter_smoke.py -q``

**建议 CI 矩阵**
| Job | 安装 | 步骤 6 文件 |
|-----|------|-------------|
| 默认 | ``poetry install`` | ``test_mcp_agent_adapter_smoke.py`` → **整模块 skip**（0 用例） |
| 全量 | ``poetry install -E mcp-agent`` | 同上 → **3 用例执行**（mock，无 Docker） |
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "tests" / "test_mcp_agent_adapter_smoke.py"


def test_ac_6_1_smoke_file_exists() -> None:
    assert SMOKE.is_file(), "test_mcp_agent_adapter_smoke.py 应存在"


def test_ac_6_2_module_importorskip_mcp_agent() -> None:
    text = SMOKE.read_text(encoding="utf-8")
    assert 'pytest.importorskip("mcp_agent")' in text
    # 置于模块前部，先于具体用例类/函数
    assert text.index("importorskip") < text.index("test_smoke")


def test_ac_6_3_smoke_tests_cover_adapter_and_step4() -> None:
    body = SMOKE.read_text(encoding="utf-8")
    assert "try_execute_via_mcp_agent" in body
    assert "run_single_turn_with_agent_llm" in body
    assert "execute_tool_dispatch" in body
    assert "test_smoke_try_execute_via_mcp_agent" in body
    assert "test_smoke_run_single_turn" in body
    assert "test_smoke_step4_execute_tool_dispatch" in body


def test_ac_6_4_docstring_documents_ci_strategy() -> None:
    head = SMOKE.read_text(encoding="utf-8")[:800]
    assert "importorskip" in head
    assert "mcp-agent" in head or "mcp_agent" in head
    assert "CI" in head or "poetry install" in head


@pytest.mark.skipif(
    importlib.util.find_spec("mcp_agent") is None,
    reason="mcp-agent extra not installed — collect-count check skipped",
)
def test_ac_6_5_collect_only_three_tests() -> None:
    src = str(ROOT / "src")
    prev = os.environ.get("PYTHONPATH", "")
    env = {
        **os.environ,
        "PYTHONPATH": f"{src}{os.pathsep}{prev}" if prev else src,
    }
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            str(SMOKE),
        ],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    out = (proc.stdout or "") + (proc.stderr or "")
    # e.g. "3 tests collected" or "collected 3 items"
    m = re.search(r"(\d+)\s+test", out)
    assert m is not None, f"unexpected collect output: {out!r}"
    assert int(m.group(1)) == 3, out
