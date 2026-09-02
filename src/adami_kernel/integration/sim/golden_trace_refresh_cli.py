"""CLI: refresh the curated golden trace suite in-place.

This is intended for maintainers:
- regenerate stable NDJSON for `report_daily`, `intake`, `tool_timeout`
- keep timestamps normalized for deterministic CI
"""

from __future__ import annotations

import argparse
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Refresh golden traces suite (writes into docs/evals/traces/*).")
    p.add_argument(
        "--traces-dir",
        type=Path,
        default=Path("docs/evals/traces"),
        help="Root traces dir (default: docs/evals/traces)",
    )
    args = p.parse_args(argv)

    from adami_kernel.integration.sim.golden_trace_capture import main as capture_main

    root = args.traces_dir
    rc = 0
    rc |= int(
        capture_main(
            [
                "--task",
                "/report run daily",
                "--out-trace",
                str(root / "report_daily" / "golden_trace.ndjson"),
                "--base-ts",
                "2000",
            ]
        )
        != 0
    )
    rc |= int(
        capture_main(
            [
                "--task",
                "/intake hello",
                "--out-trace",
                str(root / "intake" / "golden_trace.ndjson"),
                "--base-ts",
                "3000",
            ]
        )
        != 0
    )
    rc |= int(
        capture_main(
            [
                "--task",
                "/tool_timeout",
                "--out-trace",
                str(root / "tool_timeout" / "golden_trace.ndjson"),
                "--base-ts",
                "4000",
            ]
        )
        != 0
    )
    rc |= int(
        capture_main(
            [
                "--task",
                "/workflow_engine",
                "--out-trace",
                str(root / "workflow_engine" / "golden_trace.ndjson"),
                "--base-ts",
                "5000",
            ]
        )
        != 0
    )
    rc |= int(
        capture_main(
            [
                "--task",
                "/llm_call",
                "--out-trace",
                str(root / "llm_call" / "golden_trace.ndjson"),
                "--base-ts",
                "6000",
            ]
        )
        != 0
    )
    rc |= int(
        capture_main(
            [
                "--task",
                "/web_search",
                "--out-trace",
                str(root / "web_search" / "golden_trace.ndjson"),
                "--base-ts",
                "7000",
            ]
        )
        != 0
    )
    rc |= int(
        capture_main(
            [
                "--task",
                "/mcp_external",
                "--out-trace",
                str(root / "mcp_external" / "golden_trace.ndjson"),
                "--base-ts",
                "8000",
            ]
        )
        != 0
    )
    rc |= int(
        capture_main(
            [
                "--task",
                "/toolchoice",
                "--out-trace",
                str(root / "toolchoice" / "golden_trace.ndjson"),
                "--base-ts",
                "9000",
            ]
        )
        != 0
    )
    rc |= int(
        capture_main(
            [
                "--task",
                "/planner_multistep",
                "--out-trace",
                str(root / "planner_multistep" / "golden_trace.ndjson"),
                "--base-ts",
                "9500",
            ]
        )
        != 0
    )
    rc |= int(
        capture_main(
            [
                "--task",
                "/planner_multistep_mcp",
                "--out-trace",
                str(root / "planner_multistep_mcp" / "golden_trace.ndjson"),
                "--base-ts",
                "9600",
            ]
        )
        != 0
    )
    rc |= int(
        capture_main(
            [
                "--task",
                "/queue_timeout_flow",
                "--out-trace",
                str(root / "queue_timeout_flow" / "golden_trace.ndjson"),
                "--base-ts",
                "9700",
            ]
        )
        != 0
    )
    rc |= int(
        capture_main(
            [
                "--task",
                "/queue status",
                "--out-trace",
                str(root / "queue_status" / "golden_trace.ndjson"),
                "--base-ts",
                "9800",
            ]
        )
        != 0
    )
    rc |= int(
        capture_main(
            [
                "--task",
                "/queue discard",
                "--out-trace",
                str(root / "queue_discard" / "golden_trace.ndjson"),
                "--base-ts",
                "9900",
            ]
        )
        != 0
    )
    rc |= int(
        capture_main(
            [
                "--task",
                "/queue cancel",
                "--out-trace",
                str(root / "queue_cancel_noop" / "golden_trace.ndjson"),
                "--base-ts",
                "9950",
            ]
        )
        != 0
    )
    rc |= int(
        capture_main(
            [
                "--task",
                "/queue_cancel_active_flow",
                "--out-trace",
                str(root / "queue_cancel_active_flow" / "golden_trace.ndjson"),
                "--base-ts",
                "9960",
            ]
        )
        != 0
    )
    rc |= int(
        capture_main(
            [
                "--task",
                "/queue_failed_flow",
                "--out-trace",
                str(root / "queue_failed_flow" / "golden_trace.ndjson"),
                "--base-ts",
                "9965",
            ]
        )
        != 0
    )
    rc |= int(
        capture_main(
            [
                "--task",
                "/queue_budget_exceeded_flow",
                "--out-trace",
                str(root / "queue_budget_exceeded_flow" / "golden_trace.ndjson"),
                "--base-ts",
                "9966",
            ]
        )
        != 0
    )
    rc |= int(
        capture_main(
            [
                "--task",
                "/reply_dedupe_filler_flow",
                "--out-trace",
                str(root / "reply_dedupe_filler" / "golden_trace.ndjson"),
                "--base-ts",
                "9970",
            ]
        )
        != 0
    )
    return 0 if rc == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

