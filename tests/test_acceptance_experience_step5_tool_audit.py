"""验收：步骤 5（经验池 tool_call 统一审计：契约 tool_id、后端、耗时、Docker、allow 语义）。

验收方案（自动项在本文件；全链路压测见 docstring 末）
----------------------------------------------------------------
**步骤 5**
- AC-5.1 ``experience_sink.py`` 提供 ``infer_tool_audit_meta``，且 ``record_tool_call`` 支持
  ``tool_id`` / ``tool_backend`` / ``latency_ms`` / ``docker_used`` / ``mcp_allow_deny``。
- AC-5.2 ``telemetry/__init__.py`` 导出 ``infer_tool_audit_meta``。
- AC-5.3 ``EvolutionEngine.execute_tool_dispatch`` 在 ``finally`` 中调用 ``record_tool_call``（含审计字段）。
- AC-5.4 编排落点源码存在：``decision_processor``、``workflow_engine``、``multi_agent_orchestrator``
  对 ``record_tool_call`` 传入 ``infer_tool_audit_meta`` 推断字段（或等价显式字段）。
- AC-5.5 **还原性**：启用 Sink 时，一次 ``execute_tool_dispatch`` 后 Episode 内 ``tool_call`` 事件
  含 ``tool_id``、``args_summary``、``result_summary``、``tool_backend``、``latency_ms``。

**与 ``tests/test_experience_sink.py`` 的关系**
- 该文件包含 ``test_infer_tool_audit_meta_*``、``test_record_tool_call_includes_audit_fields``；
  验收执行时一并跑通。

**建议人工 / CI（本文件不强制执行）**
- 生产 ``ADAMI_EXPERIENCE_ENABLED=true`` 下跑真实 Planner/工作流，抽查 ``episodes.jsonl`` 中
  ``type=tool_call`` 是否可按 ``trace_id`` / ``tool_id`` 关联排障。
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC_SINK = ROOT / "src" / "adami_kernel" / "telemetry" / "experience_sink.py"
SRC_TELEM_INIT = ROOT / "src" / "adami_kernel" / "telemetry" / "__init__.py"
SRC_EVOLUTION = ROOT / "src" / "adami_kernel" / "cortex" / "evolution.py"
SRC_DECISION = ROOT / "src" / "adami_kernel" / "cortex" / "decision_processor.py"
SRC_WF = ROOT / "src" / "adami_kernel" / "orchestrator" / "workflow_engine.py"
SRC_MAGENT = ROOT / "src" / "adami_kernel" / "orchestrator" / "multi_agent_orchestrator.py"


def test_ac_5_1_experience_sink_audit_api() -> None:
    text = SRC_SINK.read_text(encoding="utf-8")
    assert "def infer_tool_audit_meta" in text
    assert "tool_backend" in text
    assert "latency_ms" in text
    assert "docker_used" in text
    assert "mcp_allow_deny" in text
    assert "def record_tool_call" in text


def test_ac_5_2_telemetry_package_exports_infer() -> None:
    text = SRC_TELEM_INIT.read_text(encoding="utf-8")
    assert "infer_tool_audit_meta" in text
    assert '"infer_tool_audit_meta"' in text or "'infer_tool_audit_meta'" in text


def test_ac_5_3_evolution_dispatch_finally_records() -> None:
    body = SRC_EVOLUTION.read_text(encoding="utf-8")
    assert "async def execute_tool_dispatch" in body
    assert "finally:" in body
    assert "infer_tool_audit_meta" in body
    assert "record_tool_call" in body
    assert "path" in body and "evolution.execute_tool_dispatch" in body


def test_ac_5_4_orchestration_files_wire_infer_and_record() -> None:
    for path, needle in (
        (SRC_DECISION, "decision_processor._execute_action"),
        (SRC_WF, "workflow_engine.SKILL_CALL"),
        (SRC_MAGENT, "multi_agent_orchestrator.SKILL_CALL"),
    ):
        b = path.read_text(encoding="utf-8")
        assert "infer_tool_audit_meta" in b, path.name
        assert "record_tool_call" in b, path.name
        assert needle in b, path.name


@pytest.mark.asyncio
async def test_ac_5_5_dispatch_produces_reconstructible_tool_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """一次 execute_tool_dispatch → episodes.jsonl 中可还原工具与摘要。"""
    import json
    from datetime import datetime, timezone

    from adami_kernel.telemetry.experience_aggregator import ExperienceAggregator
    from adami_kernel.telemetry.experience_sink import (
        ExperienceSink,
        reset_experience_sink_for_tests,
    )

    reset_experience_sink_for_tests()
    agg = ExperienceAggregator(tmp_path)
    sink = ExperienceSink(enabled=True, aggregator=agg)

    monkeypatch.setattr(
        "adami_kernel.telemetry.experience_sink.get_experience_sink",
        lambda: sink,
    )

    async def _no_mcp_pilot(_inv, _cap):  # noqa: ANN001
        return None

    monkeypatch.setattr(
        "adami_kernel.integration.mcp_agent.tool_executor.try_execute_via_mcp_agent",
        _no_mcp_pilot,
    )

    from adami_kernel.cortex.evolution import EvolutionEngine

    ee = EvolutionEngine(toolbox=None)

    async def _skill(**kwargs: object) -> dict:
        return {"status": "success", "data": kwargs}

    ee.dynamic_skills["AC5DEMO"] = _skill
    ee.register_tool("AC5DEMO", {"type": "object", "properties": {}}, "acceptance step5")

    sink.begin_episode("ep_ac5", "trace_ac5_root", push_context=True)
    try:
        out = await ee.execute_tool_dispatch(
            "AC5DEMO",
            {"query": "hello"},
            trace_id="trace_ac5_exec",
            chat_id="chat_ac5",
        )
        assert out == {"status": "success", "data": {"query": "hello"}}
    finally:
        sink.end_episode("ep_ac5", "success", pop_context=True)

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    jpath = tmp_path / day / "episodes.jsonl"
    assert jpath.is_file(), f"missing {jpath}"
    line = jpath.read_text(encoding="utf-8").strip().splitlines()[-1]
    doc = json.loads(line)
    assert doc["episode_id"] == "ep_ac5"
    evs = [e for e in doc["events"] if e.get("type") == "tool_call"]
    assert evs, "expected at least one tool_call event"
    p = evs[-1]["payload"]
    assert p.get("tool_id") == "AC5DEMO"
    assert "hello" in (p.get("args_summary") or "") or "query" in (p.get("args_summary") or "")
    assert p.get("result_summary")
    assert p.get("tool_backend") == "native"
    assert p.get("latency_ms") is not None
    assert p.get("docker_used") is False
    assert p.get("ok") is True
