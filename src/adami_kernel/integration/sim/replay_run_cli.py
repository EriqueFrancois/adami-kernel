"""CLI: deterministic replay runner (inject + mocks)."""

from __future__ import annotations

import argparse
from pathlib import Path

from adami_kernel.integration.sim.replay_runner import run_replay


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run deterministic replay: inject trace with mocks, export new trace.")
    p.add_argument("trace_file", type=Path, help="Input NDJSON trace file")
    p.add_argument("--out-trace", type=Path, required=True, help="Output NDJSON trace (exported)")
    p.add_argument("--chat-id", type=str, default="cli")
    p.add_argument("--platform", type=str, default="cli")
    p.add_argument(
        "--full-kernel",
        action="store_true",
        help="Inject only user prompts and let kernel run naturally (stronger, requires trace to be DP-driven).",
    )
    p.add_argument(
        "--inject-all-records",
        action="store_true",
        help="Avoid deterministic path-driving; inject prompts and rely on mocked LLM/tools to let kernel emit the full trace.",
    )
    p.add_argument(
        "--verify-isomorphic",
        action="store_true",
        help="Fail if the exported trace is not isomorphic to the input trace (after normalization).",
    )
    p.add_argument(
        "--faults",
        type=Path,
        default=None,
        help="Fault injection config JSON (phase 3) applied to the input trace before replay.",
    )
    p.add_argument(
        "--out-eval-json",
        type=Path,
        default=None,
        help="Write eval report JSON for the replayed trace (defaults next to --out-trace if --faults is set).",
    )
    p.add_argument(
        "--out-eval-md",
        type=Path,
        default=None,
        help="Write eval report Markdown for the replayed trace (defaults next to --out-trace if --faults is set).",
    )
    p.add_argument(
        "--eval-assertions",
        type=Path,
        default=None,
        help="Assertions pack to evaluate the replayed trace (defaults to sibling assertions.json).",
    )
    p.add_argument(
        "--eval-scorecard",
        type=Path,
        default=None,
        help="Scorecard file to evaluate the replayed trace (defaults to sibling scorecard.json).",
    )
    args = p.parse_args(argv)

    import asyncio

    from adami_kernel.integration.sim.replay import (
        apply_faults_to_records,
        load_fault_injection_options,
        load_ndjson_records,
    )
    from adami_kernel.integration.sim.replay_eval import evaluate_trace_file, render_markdown_report

    faults = load_fault_injection_options(args.faults) if args.faults is not None else None

    asyncio.run(
        run_replay(
            trace_file=args.trace_file,
            out_trace=args.out_trace,
            chat_id=str(args.chat_id),
            platform=str(args.platform),
            full_kernel=bool(args.full_kernel),
            verify_isomorphic=bool(args.verify_isomorphic),
            faults=faults,
            inject_all_records=bool(args.inject_all_records),
        )
    )

    if faults is not None and faults.enabled:
        # Apply faults to the exported trace (so we can simulate regressions in emitted events).
        recs = load_ndjson_records(Path(args.out_trace))
        recs2 = apply_faults_to_records(recs, faults)
        Path(args.out_trace).write_text("".join([r.to_ndjson_line() for r in recs2]), encoding="utf-8")

    # If faults are used, produce an eval report by default (or when explicitly requested).
    want_eval = args.faults is not None or args.out_eval_json is not None or args.out_eval_md is not None
    if not want_eval:
        return 0

    base_dir = Path(args.trace_file).parent
    assertions = args.eval_assertions or (base_dir / "assertions.json")
    scorecard = args.eval_scorecard or (base_dir / "scorecard.json")

    out_eval_json = args.out_eval_json
    out_eval_md = args.out_eval_md
    if out_eval_json is None and args.faults is not None:
        out_eval_json = Path(args.out_trace).with_suffix(".eval.json")
    if out_eval_md is None and args.faults is not None:
        out_eval_md = Path(args.out_trace).with_suffix(".eval.md")

    res = evaluate_trace_file(
        trace_file=Path(args.out_trace),
        assertions_file=assertions if assertions.is_file() else None,
        scorecard_file=scorecard if scorecard.is_file() else None,
    )
    if out_eval_json is not None:
        out_eval_json.parent.mkdir(parents=True, exist_ok=True)
        out_eval_json.write_text(res.to_json() + "\n", encoding="utf-8")
    if out_eval_md is not None:
        out_eval_md.parent.mkdir(parents=True, exist_ok=True)
        out_eval_md.write_text(
            render_markdown_report(
                trace_file=Path(args.out_trace),
                assertions_file=assertions if assertions.is_file() else None,
                forbid_strings=(),
                result=res,
            )
            + "\n",
            encoding="utf-8",
        )
    return 0 if res.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())

