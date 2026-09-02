from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple


@dataclass(frozen=True)
class CompareSummary:
    ok: bool
    regressions: tuple[str, ...]
    improvements: tuple[str, ...]
    baseline_score: int
    head_score: int

    def to_json(self) -> str:
        return json.dumps(
            {
                "ok": self.ok,
                "regressions": list(self.regressions),
                "improvements": list(self.improvements),
                "baseline_score": self.baseline_score,
                "head_score": self.head_score,
            },
            ensure_ascii=False,
        )


def _load(path: Path) -> Dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("suite report must be a JSON object")
    return raw


def _trace_map(report: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    traces = report.get("traces") or []
    out: Dict[str, Dict[str, Any]] = {}
    if not isinstance(traces, list):
        return out
    for t in traces:
        if not isinstance(t, dict):
            continue
        name = str(t.get("name") or "").strip()
        res = t.get("result")
        if not name or not isinstance(res, dict):
            continue
        out[name] = res
    return out


def _score(res: Dict[str, Any]) -> int:
    try:
        return int(res.get("score", 0))
    except Exception:
        return 0


def _ok(res: Dict[str, Any]) -> bool:
    return bool(res.get("ok", False))


def _dims(res: Dict[str, Any]) -> Dict[str, int]:
    sc = res.get("scorecard") if isinstance(res.get("scorecard"), dict) else {}
    out: Dict[str, int] = {}
    for k in ("correctness", "safety", "ux", "noise"):
        try:
            out[k] = int(sc.get(k, 0))
        except Exception:
            out[k] = 0
    return out


def compare_suite_reports(
    *,
    baseline_json: Path,
    head_json: Path,
    fail_on_score_drop: bool = True,
    fail_on_new_failure: bool = True,
    max_score_drop: int = 0,
    max_dim_drop: int = 0,
) -> Tuple[CompareSummary, str]:
    """Compare two `adami-replay-eval --suite-dir` JSON outputs.

    Policy:
    - Any trace ok->false is a regression.
    - Any trace score drop greater than `max_score_drop` is a regression (unless disabled).
    - Any dimension score drop greater than `max_dim_drop` is a regression (unless score-drop disabled).
    - New failures in `failures[]` is a regression (unless disabled).
    """
    base = _load(baseline_json)
    head = _load(head_json)

    base_score = _score(base)
    head_score = _score(head)
    base_tr = _trace_map(base)
    head_tr = _trace_map(head)

    regressions: list[str] = []
    improvements: list[str] = []

    all_names = sorted(set(base_tr.keys()) | set(head_tr.keys()))
    for name in all_names:
        b = base_tr.get(name)
        h = head_tr.get(name)
        if b is None:
            improvements.append(f"new_trace:{name}")
            continue
        if h is None:
            regressions.append(f"missing_trace:{name}")
            continue

        b_ok, h_ok = _ok(b), _ok(h)
        if b_ok and not h_ok:
            regressions.append(f"trace_ok_to_fail:{name}")
        elif (not b_ok) and h_ok:
            improvements.append(f"trace_fail_to_ok:{name}")

        b_score, h_score = _score(b), _score(h)
        if fail_on_score_drop and h_score < b_score:
            drop = b_score - h_score
            if drop > int(max_score_drop):
                regressions.append(
                    f"trace_score_drop:{name}:{b_score}->{h_score}(-{drop} > {int(max_score_drop)})"
                )
        elif h_score > b_score:
            improvements.append(f"trace_score_up:{name}:{b_score}->{h_score}")

        if fail_on_score_drop:
            bd, hd = _dims(b), _dims(h)
            for k in ("correctness", "safety", "ux", "noise"):
                if hd.get(k, 0) < bd.get(k, 0):
                    drop = bd.get(k, 0) - hd.get(k, 0)
                    if drop <= int(max_dim_drop):
                        continue
                    regressions.append(
                        f"trace_dim_drop:{name}:{k}:{bd.get(k,0)}->{hd.get(k,0)}(-{drop} > {int(max_dim_drop)})"
                    )
                elif hd.get(k, 0) > bd.get(k, 0):
                    improvements.append(
                        f"trace_dim_up:{name}:{k}:{bd.get(k,0)}->{hd.get(k,0)}"
                    )

        if fail_on_new_failure:
            b_fail = set(b.get("failures") or [])
            h_fail = set(h.get("failures") or [])
            if h_fail - b_fail:
                regressions.append(
                    f"trace_new_failures:{name}:{sorted(h_fail - b_fail)}"
                )

    if fail_on_score_drop and head_score < base_score:
        drop = base_score - head_score
        if drop > int(max_score_drop):
            regressions.append(
                f"suite_score_drop:{base_score}->{head_score}(-{drop} > {int(max_score_drop)})"
            )
    elif head_score > base_score:
        improvements.append(f"suite_score_up:{base_score}->{head_score}")

    ok = len(regressions) == 0
    md = render_compare_markdown(
        baseline_path=baseline_json,
        head_path=head_json,
        baseline_score=base_score,
        head_score=head_score,
        regressions=tuple(regressions),
        improvements=tuple(improvements),
        baseline_compat=base.get("compat") if isinstance(base.get("compat"), dict) else None,
        head_compat=head.get("compat") if isinstance(head.get("compat"), dict) else None,
    )
    return (
        CompareSummary(
            ok=ok,
            regressions=tuple(regressions),
            improvements=tuple(improvements),
            baseline_score=base_score,
            head_score=head_score,
        ),
        md,
    )


def render_compare_markdown(
    *,
    baseline_path: Path,
    head_path: Path,
    baseline_score: int,
    head_score: int,
    regressions: Iterable[str],
    improvements: Iterable[str],
    baseline_compat: Optional[Dict[str, Any]] = None,
    head_compat: Optional[Dict[str, Any]] = None,
) -> str:
    reg = list(regressions)
    imp = list(improvements)
    lines: list[str] = []
    lines.append("## Replay compare report")
    lines.append("")

    base_mode = str((baseline_compat or {}).get("mode") or "").strip().lower()
    head_mode = str((head_compat or {}).get("mode") or "").strip().lower()
    if base_mode == "fallback":
        reason = str((baseline_compat or {}).get("reason") or "unknown").strip()
        lines.append("> **Note**: baseline is **not evaluable** (compat fallback).")
        lines.append(
            f"> This compare run is for **new capability visibility only**; regressions against baseline are not meaningful. (reason: `{reason}`)"
        )
        lines.append("")
    if head_mode == "fallback":
        reason = str((head_compat or {}).get("reason") or "unknown").strip()
        lines.append("> **Note**: head is **not evaluable** (compat fallback).")
        lines.append(f"> Compare results may be incomplete. (reason: `{reason}`)")
        lines.append("")

    lines.append(f"- Baseline: `{baseline_path}` (score={baseline_score})")
    lines.append(f"- Head: `{head_path}` (score={head_score})")
    lines.append("")
    if reg:
        lines.append("### Regressions")
        for r in reg:
            lines.append(f"- **{r}**")
        lines.append("")
    else:
        lines.append("### Regressions")
        lines.append("- (none)")
        lines.append("")
    if imp:
        lines.append("### Improvements")
        for i in imp:
            lines.append(f"- **{i}**")
        lines.append("")
    else:
        lines.append("### Improvements")
        lines.append("- (none)")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"

