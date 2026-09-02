from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Compare replay-eval suite results (JSON or git refs).")
    p.add_argument("--baseline-json", type=Path, default=None)
    p.add_argument("--head-json", type=Path, default=None)
    p.add_argument("--baseline-ref", type=str, default=None, help="Git ref for baseline eval (e.g. v1.0-alpha)")
    p.add_argument("--head-ref", type=str, default=None, help="Git ref for head eval (e.g. HEAD)")
    p.add_argument(
        "--suite-dir",
        type=Path,
        default=Path("docs/evals/traces"),
        help="Suite dir to evaluate when using --baseline-ref/--head-ref (default: docs/evals/traces)",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Directory to write baseline/head/compare artifacts when using refs",
    )
    p.add_argument("--out-json", type=Path, default=None)
    p.add_argument("--out-md", type=Path, default=None)
    p.add_argument("--no-fail-on-score-drop", action="store_true")
    p.add_argument("--no-fail-on-new-failure", action="store_true")
    p.add_argument(
        "--max-score-drop",
        type=int,
        default=0,
        help="Allow score drops up to this value before failing (default: 0).",
    )
    p.add_argument(
        "--max-dim-drop",
        type=int,
        default=0,
        help="Allow per-dimension drops up to this value before failing (default: 0).",
    )
    args = p.parse_args(argv)

    # Mode A: compare existing JSON outputs
    if args.baseline_json is not None and args.head_json is not None:
        from adami_kernel.integration.sim.replay_compare import compare_suite_reports

        summary, md = compare_suite_reports(
            baseline_json=args.baseline_json,
            head_json=args.head_json,
            fail_on_score_drop=not bool(args.no_fail_on_score_drop),
            fail_on_new_failure=not bool(args.no_fail_on_new_failure),
            max_score_drop=int(args.max_score_drop),
            max_dim_drop=int(args.max_dim_drop),
        )
    # Mode B: baseline/head refs (evaluate then compare)
    elif args.baseline_ref and args.head_ref:
        from adami_kernel.integration.sim.replay_compare_refs import compare_refs

        out_dir = args.out_dir or Path("reports/replay_compare_refs")
        _, _, cmp_json, cmp_md, summary_text = compare_refs(
            baseline_ref=str(args.baseline_ref),
            head_ref=str(args.head_ref),
            suite_dir=Path(args.suite_dir),
            out_dir=Path(out_dir),
            max_score_drop=int(args.max_score_drop),
            max_dim_drop=int(args.max_dim_drop),
        )
        # Reuse file-based outputs for uniform CLI behavior.
        if args.out_json:
            args.out_json.parent.mkdir(parents=True, exist_ok=True)
            args.out_json.write_text(summary_text + "\n", encoding="utf-8")
        if args.out_md:
            args.out_md.parent.mkdir(parents=True, exist_ok=True)
            args.out_md.write_text(cmp_md.read_text(encoding="utf-8"), encoding="utf-8")
        # Also print summary JSON (already includes ok flag).
        print(summary_text)
        # Exit code mirrors summary.ok.
        import json as _json

        ok = bool(_json.loads(summary_text).get("ok", False))
        return 0 if ok else 2
    else:
        print(
            "error: provide either (--baseline-json and --head-json) or (--baseline-ref and --head-ref)",
            file=sys.stderr,
        )
        return 2

    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(summary.to_json() + "\n", encoding="utf-8")
    if args.out_md:
        args.out_md.parent.mkdir(parents=True, exist_ok=True)
        args.out_md.write_text(md, encoding="utf-8")

    if not summary.ok:
        print(summary.to_json(), file=sys.stderr)
        return 2
    print(summary.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

