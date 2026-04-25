"""验收：步骤 6（删除与收敛）。

目标：删除重复导出路径（旧 trace HTTP URL），保留单一事实来源（v1 NDJSON），Sim 仅作为消费者之一。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ac_sim_6_1_no_dead_config_trace_http_url() -> None:
    """Grep 无残留：变量/文档/代码均不应出现该旧通道。"""
    needle = "ADAMI_SIM_TRACE_" + "HTTP_URL"
    for p in [
        ROOT / "src",
        ROOT / "docs",
        ROOT / "tests",
        ROOT / ".env.example",
    ]:
        text = p.read_text(encoding="utf-8") if p.is_file() else ""
        if p.is_dir():
            for fp in p.rglob("*"):
                if fp.is_file() and fp.suffix in {
                    ".py",
                    ".md",
                    ".toml",
                    ".yml",
                    ".yaml",
                    ".example",
                }:
                    if fp.name == Path(__file__).name:
                        continue
                    if needle in fp.read_text(encoding="utf-8", errors="ignore"):
                        raise AssertionError(f"found {needle} in {fp}")
        else:
            assert needle not in text


def test_ac_sim_6_2_trace_sink_flush_only_writes_and_webhook() -> None:
    body = (ROOT / "src" / "adami_kernel" / "integration" / "sim" / "trace_sink.py").read_text(
        encoding="utf-8"
    )
    assert "post_sim_trace_webhook" in body
    assert "application/x-ndjson" not in body


def test_ac_sim_6_3_plan_mentions_single_source_ndjson_v1() -> None:
    t = (ROOT / "docs" / "sim_integration_plan.md").read_text(encoding="utf-8")
    assert "adami_replay_trace.v1" in t
    assert "NDJSON" in t
