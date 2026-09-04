"""CLI: evaluate NDJSON replay trace with assertions + scorecard."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate AdamI replay trace (vNext minimal).")
    parser.add_argument(
        "trace_file",
        type=Path,
        nargs="?",
        default=None,
        help="Path to .ndjson trace file (optional if --suite-dir is provided)",
    )
    parser.add_argument(
        "--suite-dir",
        type=Path,
        default=None,
        help="Evaluate a suite directory (each child dir containing golden_trace.ndjson)",
    )
    parser.add_argument(
        "--assertions",
        type=Path,
        default=None,
        help="Path to JSON assertions pack (optional)",
    )
    parser.add_argument(
        "--forbid",
        action="append",
        default=[],
        help="Forbidden substring (repeatable). If found in any record JSON, fail.",
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        default=None,
        help="Write machine-readable report JSON to this path",
    )
    parser.add_argument(
        "--out-md",
        type=Path,
        default=None,
        help="Write Markdown report to this path",
    )
    args = parser.parse_args(argv)

    from adami_kernel.integration.sim.replay_eval import (
        evaluate_suite_dir,
        evaluate_trace_file,
        render_markdown_report,
        render_suite_markdown_report,
    )

    if args.suite_dir is not None:
        suite_result = evaluate_suite_dir(suite_dir=args.suite_dir, forbid_strings=args.forbid)
        if args.out_json:
            args.out_json.parent.mkdir(parents=True, exist_ok=True)
            args.out_json.write_text(suite_result.to_json() + "\n", encoding="utf-8")
        if args.out_md:
            args.out_md.parent.mkdir(parents=True, exist_ok=True)
            args.out_md.write_text(
                render_suite_markdown_report(
                    suite_dir=args.suite_dir,
                    forbid_strings=tuple(str(x) for x in args.forbid),
                    result=suite_result,
                )
                + "\n",
                encoding="utf-8",
            )
        if not suite_result.ok:
            print(suite_result.to_json(), file=sys.stderr)
            return 2
        print(suite_result.to_json())
        return 0

    if args.trace_file is None:
        print("error: provide trace_file or --suite-dir", file=sys.stderr)
        return 2

    result = evaluate_trace_file(
        trace_file=args.trace_file,
        assertions_file=args.assertions,
        forbid_strings=args.forbid,
    )

    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(result.to_json() + "\n", encoding="utf-8")
    if args.out_md:
        args.out_md.parent.mkdir(parents=True, exist_ok=True)
        args.out_md.write_text(
            render_markdown_report(
                trace_file=args.trace_file,
                assertions_file=args.assertions,
                forbid_strings=tuple(str(x) for x in args.forbid),
                result=result,
            )
            + "\n",
            encoding="utf-8",
        )

    if not result.ok:
        print(result.to_json(), file=sys.stderr)
        return 2
    print(result.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

