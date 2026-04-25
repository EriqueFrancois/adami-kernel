"""经验池 sink / 脱敏 / 并发写入单测。"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from adami_kernel.telemetry.experience_aggregator import ExperienceAggregator
from adami_kernel.telemetry.experience_sink import (
    ExperienceRecord,
    ExperienceSink,
    fingerprint_payload,
    infer_tool_audit_meta,
    redact_payload,
    redact_text,
    summarize_text,
)


def test_redact_api_key_pattern() -> None:
    raw = "use sk-abcdefghijklmnopqrstuvwxyz1234567890abcd here"
    out = redact_text(raw)
    assert "sk-" not in out.lower()
    assert "REDACTED" in out or "[REDACTED" in out


def test_redact_payload_masks_nested_secret() -> None:
    obj = {"ok": True, "api_key": "supersecret", "nested": {"label": "x"}}
    r = redact_payload(obj)
    assert r["api_key"] == "[REDACTED]"
    assert r["nested"]["label"] == "x"


def test_fingerprint_stable_for_secrets() -> None:
    """脱敏后相同结构应得到相同指纹（不泄露具体密钥串）。"""
    p1 = {"task": "hi", "api_key": "aaaa"}
    p2 = {"task": "hi", "api_key": "bbbb"}
    assert fingerprint_payload(p1) == fingerprint_payload(p2)


def test_experience_record_model() -> None:
    rec = ExperienceRecord(
        trace_id="t1",
        episode_id="e1",
        type="feedback",
        payload={"reward": 0.3},
        payload_sha256="abc",
    )
    d = rec.model_dump()
    assert d["type"] == "feedback"
    assert d["episode_id"] == "e1"


def test_summarize_truncates() -> None:
    long = "x" * 5000
    s = summarize_text(long, head=100)
    assert len(s) <= 101
    assert "…" in s or len(s) < len(long)


def test_concurrent_writes_no_crash(tmp_path: Path) -> None:
    """并发 record_feedback 不应抛异常；收口后 jsonl 可读。"""
    agg = ExperienceAggregator(tmp_path)
    sink = ExperienceSink(enabled=True, aggregator=agg)
    eid = "ep_concurrent"

    async def burst(worker: int) -> None:
        for i in range(30):
            sink.record_feedback(
                trace_id=f"w{worker}_t{i}",
                episode_id=eid,
                reward=0.1 * (i % 5),
                metadata={"worker": worker, "i": i},
                source="test",
            )

    async def main() -> None:
        await asyncio.gather(*[burst(w) for w in range(8)])

    asyncio.run(main())
    sink.end_episode(eid, "success", pop_context=False)

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    jpath = tmp_path / day / "episodes.jsonl"
    assert jpath.is_file(), f"missing {jpath}"
    line = jpath.read_text(encoding="utf-8").strip().splitlines()[-1]
    doc = json.loads(line)
    assert doc["episode_id"] == eid
    assert doc["status"] == "success"
    assert len(doc["events"]) == 8 * 30


def test_infer_tool_audit_meta_native_and_mcp() -> None:
    class _Reg:
        def __init__(self) -> None:
            from adami_kernel.integration.mcp_agent.contracts import (
                tool_capability_mcp,
                tool_capability_native,
            )

            self._mcp = tool_capability_mcp(
                "MCP.SRV.ECHO",
                {"type": "object", "properties": {}},
                "d",
                "srv",
                "echo",
            )
            self._nat = tool_capability_native(
                "WEB_SEARCH",
                {"type": "object", "properties": {}},
                "search",
            )

        def get(self, tid: str):
            u = tid.upper()
            if u == "MCP.SRV.ECHO":
                return self._mcp
            if u == "WEB_SEARCH":
                return self._nat
            return None

    class _EE:
        tool_contract_registry = _Reg()

    ee = _EE()
    m_native = infer_tool_audit_meta(ee, "web_search")
    assert m_native["tool_id"] == "WEB_SEARCH"
    assert m_native["tool_backend"] == "native"
    assert m_native["docker_used"] is False

    m_mcp = infer_tool_audit_meta(ee, "mcp.srv.echo")
    assert m_mcp["tool_backend"] == "mcp_docker"
    assert m_mcp["docker_used"] is True
    assert m_mcp["mcp_allow_deny"] == "allowlist_registered"

    m_agent = infer_tool_audit_meta(ee, "WEB_SEARCH", override_backend="mcp_agent")
    assert m_agent["tool_backend"] == "mcp_agent"
    assert m_agent["docker_used"] is True


def test_record_tool_call_includes_audit_fields(tmp_path: Path) -> None:
    agg = ExperienceAggregator(tmp_path)
    sink = ExperienceSink(enabled=True, aggregator=agg)
    eid = "ep_tool_audit"
    sink.begin_episode(eid, "trace_root", push_context=False)
    sink.record_tool_call(
        trace_id="t_tool",
        episode_id=eid,
        tool_name="MCP.X.Y",
        tool_id="MCP.X.Y",
        args_summary='{"msg":"hi"}',
        result_summary="ok",
        ok=True,
        tool_backend="mcp_agent",
        latency_ms=12.3456,
        docker_used=True,
        mcp_allow_deny="allowlist_registered",
        extra={"path": "test"},
    )
    sink.end_episode(eid, "success", pop_context=False)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = (tmp_path / day / "episodes.jsonl").read_text(encoding="utf-8").strip().splitlines()
    doc = json.loads(lines[-1])
    ev = doc["events"][-1]
    assert ev["type"] == "tool_call"
    p = ev["payload"]
    assert p["tool_id"] == "MCP.X.Y"
    assert p["tool_backend"] == "mcp_agent"
    assert p["latency_ms"] == 12.346
    assert p["docker_used"] is True
    assert p["mcp_allow_deny"] == "allowlist_registered"
    assert p["args_summary"]


def test_sk_key_not_in_summarize() -> None:
    text = "error: Bearer abcdefghijklmnop token sk-1234567890123456789012345678901234567890"
    s = summarize_text(text)
    assert re.search(r"sk-[a-zA-Z0-9]{10,}", s) is None
