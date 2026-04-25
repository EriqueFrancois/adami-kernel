"""CLI：校验 NDJSON 轨迹（步骤 2 阶段 1）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate AdamI replay trace NDJSON (phase 1).")
    parser.add_argument("trace_file", type=Path, help="Path to .ndjson trace file")
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Allow empty file without records",
    )
    parser.add_argument(
        "--no-monotonic-ts",
        action="store_true",
        help="Do not require non-decreasing ts",
    )
    args = parser.parse_args(argv)

    from adami_kernel.integration.sim.replay import (
        ReplayValidationError,
        load_ndjson_records,
        validate_phase1_records,
    )

    try:
        records = load_ndjson_records(args.trace_file)
        validate_phase1_records(
            records,
            allow_empty=args.allow_empty,
            monotonic_ts=not args.no_monotonic_ts,
        )
    except ReplayValidationError as e:
        print(f"VALIDATION_FAILED: {e}", file=sys.stderr)
        return 2
    print(f"OK {len(records)} record(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
