#!/usr/bin/env python3
"""模块四步骤 7：从 Sim 导出的 NDJSON 统计阶段边界与 checkpoint 序号（可对接 CI / 演示）。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def summarize_lines(lines: List[str]) -> Dict[str, Any]:
    n_phase_events = 0
    n_with_seq = 0
    phases_seen: List[str] = []
    seqs: List[int] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        pr = row.get("payload_redacted") or {}
        if not isinstance(pr, dict):
            continue
        if pr.get("event_type") != "PHASE_TRANSITION":
            continue
        n_phase_events += 1
        top_ph = row.get("phase") or pr.get("phase") or pr.get("to_phase")
        if isinstance(top_ph, str):
            phases_seen.append(top_ph)
        cs = row.get("checkpoint_seq")
        if cs is not None:
            try:
                seqs.append(int(cs))
                n_with_seq += 1
            except (TypeError, ValueError):
                pass
    return {
        "phase_transition_events": n_phase_events,
        "with_top_level_checkpoint_seq": n_with_seq,
        "phases_sequence": phases_seen,
        "checkpoint_seqs": seqs,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "path",
        nargs="?",
        help="NDJSON 文件路径；省略则从 stdin 读",
    )
    args = ap.parse_args()
    if args.path:
        text = Path(args.path).read_text(encoding="utf-8")
        lines = text.splitlines()
    else:
        lines = sys.stdin.read().splitlines()
    out = summarize_lines(lines)
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
