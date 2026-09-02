"""Replay eval (vNext minimal subset): phase1 validate + assertions + scorecard report.

This module builds on ``integration.sim.replay`` which already provides:
- NDJSON loading + schema validation
- assertion DSL
- inject skeleton

The goal here is to make replay runnable as a **CI gate**: stable exit codes and machine-readable report.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from adami_kernel.integration.sim.replay import (
    ReplayValidationError,
    TraceAssertion,
    apply_assertions,
    load_ndjson_records,
    trace_assertion_from_mapping,
    validate_phase1_records,
)
from adami_kernel.integration.sim.schema import ReplayTraceRecordV1


@dataclass(frozen=True)
class ScorecardSpec:
    min_correctness: int = 100
    min_safety: int = 100
    min_ux: int = 80
    min_noise: int = 100
    # New (roadmap): operability gates (defaults are non-gating).
    min_operability: int = 0
    # New (Milestone B): performance & cost gates (defaults are non-gating).
    min_latency: int = 0
    min_cost: int = 0
    # Stable metric-style gates (optional; None = no gate).
    max_tool_latency_ms_total: Optional[int] = None
    max_llm_calls: Optional[int] = None
    max_duration_sec: float = 10.0
    weights: dict[str, float] = field(default_factory=dict)
    _provided: frozenset[str] = field(default_factory=frozenset, repr=False)

    @staticmethod
    def from_path(path: Path) -> "ScorecardSpec":
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("scorecard must be a JSON object")
        w = raw.get("weights") if isinstance(raw.get("weights"), dict) else {}
        mtl = raw.get("max_tool_latency_ms_total", None)
        mlc = raw.get("max_llm_calls", None)
        return ScorecardSpec(
            min_correctness=int(raw.get("min_correctness", 100)),
            min_safety=int(raw.get("min_safety", 100)),
            min_ux=int(raw.get("min_ux", 80)),
            min_noise=int(raw.get("min_noise", 100)),
            min_operability=int(raw.get("min_operability", 0)),
            min_latency=int(raw.get("min_latency", 0)),
            min_cost=int(raw.get("min_cost", 0)),
            max_tool_latency_ms_total=int(mtl) if mtl is not None else None,
            max_llm_calls=int(mlc) if mlc is not None else None,
            max_duration_sec=float(raw.get("max_duration_sec", 10.0)),
            weights={str(k): float(v) for k, v in w.items()},
            _provided=frozenset(raw.keys()),
        )

    @staticmethod
    def from_mapping(raw: dict[str, Any]) -> "ScorecardSpec":
        if not isinstance(raw, dict):
            raise ValueError("scorecard must be an object")
        w = raw.get("weights") if isinstance(raw.get("weights"), dict) else {}
        mtl = raw.get("max_tool_latency_ms_total", None)
        mlc = raw.get("max_llm_calls", None)
        return ScorecardSpec(
            min_correctness=int(raw.get("min_correctness", 100)),
            min_safety=int(raw.get("min_safety", 100)),
            min_ux=int(raw.get("min_ux", 80)),
            min_noise=int(raw.get("min_noise", 100)),
            min_operability=int(raw.get("min_operability", 0)),
            min_latency=int(raw.get("min_latency", 0)),
            min_cost=int(raw.get("min_cost", 0)),
            max_tool_latency_ms_total=int(mtl) if mtl is not None else None,
            max_llm_calls=int(mlc) if mlc is not None else None,
            max_duration_sec=float(raw.get("max_duration_sec", 10.0)),
            weights={str(k): float(v) for k, v in w.items()},
            _provided=frozenset(raw.keys()),
        )

    def merged_over(self, base: "ScorecardSpec") -> "ScorecardSpec":
        """Overlay `self` over `base` (trace-specific overrides)."""
        w = dict(base.weights)
        if "weights" in self._provided:
            w.update(self.weights or {})
        return ScorecardSpec(
            min_correctness=int(self.min_correctness if "min_correctness" in self._provided else base.min_correctness),
            min_safety=int(self.min_safety if "min_safety" in self._provided else base.min_safety),
            min_ux=int(self.min_ux if "min_ux" in self._provided else base.min_ux),
            min_noise=int(self.min_noise if "min_noise" in self._provided else base.min_noise),
            min_operability=int(
                self.min_operability if "min_operability" in self._provided else base.min_operability
            ),
            min_latency=int(self.min_latency if "min_latency" in self._provided else base.min_latency),
            min_cost=int(self.min_cost if "min_cost" in self._provided else base.min_cost),
            max_tool_latency_ms_total=(
                int(self.max_tool_latency_ms_total) if "max_tool_latency_ms_total" in self._provided else base.max_tool_latency_ms_total
            ),
            max_llm_calls=(
                int(self.max_llm_calls) if "max_llm_calls" in self._provided else base.max_llm_calls
            ),
            max_duration_sec=float(
                self.max_duration_sec if "max_duration_sec" in self._provided else base.max_duration_sec
            ),
            weights=w,
            _provided=base._provided | self._provided,
        )

    def normalized_weights(self) -> dict[str, float]:
        base = {
            "correctness": 0.35,
            "safety": 0.25,
            "ux": 0.2,
            "noise": 0.1,
            # New (roadmap): operability (tool lifecycle + error surfacing)
            "operability": 0.05,
            # New (Milestone B): keep small weights by default; enable as CI gates via thresholds.
            "latency": 0.05,
            "cost": 0.05,
        }
        base.update({k: v for k, v in (self.weights or {}).items() if k in base and v >= 0})
        s = sum(base.values()) or 1.0
        return {k: (v / s) for k, v in base.items()}


@dataclass(frozen=True)
class TemplateRules:
    require_reply_after_timeout: bool = False
    require_reply_after_error: bool = False
    require_no_filler_reply: bool = False
    require_tool_field_on_tool_calls: bool = False
    require_actionable_reply_on_tool_failure: bool = False
    actionable_reply_keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class TemplateSpec:
    name: str
    applies_payload_event_type: Optional[str] = None
    applies_payload_event_type_prefix: Optional[str] = None
    scorecard_defaults: Optional[ScorecardSpec] = None
    assertions_append: tuple[tuple[int, TraceAssertion], ...] = ()
    rules: TemplateRules = TemplateRules()

    @staticmethod
    def from_path(path: Path) -> "TemplateSpec":
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("template must be a JSON object")
        name = str(raw.get("name") or path.stem)
        aw = raw.get("applies_when") if isinstance(raw.get("applies_when"), dict) else {}
        applies_ev = aw.get("payload_event_type")
        applies_prefix = aw.get("payload_event_type_prefix")
        sd = raw.get("scorecard_defaults") if isinstance(raw.get("scorecard_defaults"), dict) else None
        sc = ScorecardSpec.from_mapping(sd) if sd else None
        rules_raw = raw.get("rules") if isinstance(raw.get("rules"), dict) else {}
        rules = TemplateRules(
            require_reply_after_timeout=bool(rules_raw.get("require_reply_after_timeout")),
            require_reply_after_error=bool(rules_raw.get("require_reply_after_error")),
            require_no_filler_reply=bool(rules_raw.get("require_no_filler_reply")),
            require_tool_field_on_tool_calls=bool(rules_raw.get("require_tool_field_on_tool_calls")),
            require_actionable_reply_on_tool_failure=bool(
                rules_raw.get("require_actionable_reply_on_tool_failure")
            ),
            actionable_reply_keywords=tuple(
                str(x)
                for x in (raw.get("actionable_reply_keywords") or [])
                if str(x).strip()
            ),
        )
        ap = raw.get("assertions_append")
        append: list[tuple[int, TraceAssertion]] = []
        if isinstance(ap, list):
            # Reuse the same pack shape as assertions.json
            tmp_path = path  # for error messages
            for i, item in enumerate(ap):
                if not isinstance(item, dict):
                    raise ValueError(f"{tmp_path.name}.assertions_append[{i}] must be an object")
                idx = item.get("index")
                mapping = item.get("assertion")
                if not isinstance(idx, int):
                    raise ValueError(f"{tmp_path.name}.assertions_append[{i}].index must be int")
                if not isinstance(mapping, dict):
                    raise ValueError(f"{tmp_path.name}.assertions_append[{i}].assertion must be object")
                append.append((idx, trace_assertion_from_mapping(mapping)))
        return TemplateSpec(
            name=name,
            applies_payload_event_type=str(applies_ev) if applies_ev else None,
            applies_payload_event_type_prefix=str(applies_prefix) if applies_prefix else None,
            scorecard_defaults=sc,
            assertions_append=tuple(append),
            rules=rules,
        )


@dataclass(frozen=True)
class SuiteEvalResult:
    ok: bool
    score: int
    failures: tuple[str, ...]
    traces: tuple[tuple[str, EvalResult], ...]

    def to_json(self) -> str:
        return json.dumps(
            {
                "ok": self.ok,
                "score": self.score,
                "failures": list(self.failures),
                "traces": [
                    {"name": name, "result": json.loads(res.to_json())} for name, res in self.traces
                ],
            },
            ensure_ascii=False,
            indent=2,
        )


@dataclass(frozen=True)
class EvalResult:
    ok: bool
    score: int
    failures: tuple[str, ...]
    n_records: int
    n_assertions: int
    n_forbid_hits: int
    n_noise_hits: int
    tool_calls: int
    tool_latency_ms_total: int
    llm_calls: int
    llm_latency_ms_total: int
    duration_sec: float
    correctness_score: int
    safety_score: int
    ux_score: int
    noise_score: int
    operability_score: int
    latency_score: int
    cost_score: int

    def to_json(self) -> str:
        return json.dumps(
            {
                "ok": self.ok,
                "score": self.score,
                "failures": list(self.failures),
                "n_records": self.n_records,
                "n_assertions": self.n_assertions,
                "n_forbid_hits": self.n_forbid_hits,
                "n_noise_hits": self.n_noise_hits,
                "metrics": {
                    "tool_calls": self.tool_calls,
                    "tool_latency_ms_total": self.tool_latency_ms_total,
                    "llm_calls": self.llm_calls,
                    "llm_latency_ms_total": self.llm_latency_ms_total,
                },
                "duration_sec": self.duration_sec,
                "scorecard": {
                    "correctness": self.correctness_score,
                    "safety": self.safety_score,
                    "ux": self.ux_score,
                    "noise": self.noise_score,
                    "operability": self.operability_score,
                    "latency": self.latency_score,
                    "cost": self.cost_score,
                },
            },
            ensure_ascii=False,
            indent=2,
        )


def _operability_score(*, records: Sequence[ReplayTraceRecordV1], template_rules: TemplateRules) -> int:
    """Operability: tool lifecycle completeness + user-visible failure handling.

    This score is intentionally mechanical so it can be gated in CI.
    """
    tool_missing = 0
    lifecycle_mismatch = 0
    starts: dict[str, int] = {}
    for r in records:
        p = r.payload_redacted or {}
        et = p.get("event_type")
        if not isinstance(et, str) or not et.startswith("TOOL_CALL_"):
            continue
        tool = p.get("tool")
        # Operability baseline: any TOOL_CALL_* should carry tool identity.
        if not tool:
            tool_missing += 1
            continue
        tool_s = str(tool or "tool.unknown")
        if et == "TOOL_CALL_START":
            starts[tool_s] = starts.get(tool_s, 0) + 1
        elif et in ("TOOL_CALL_DONE", "TOOL_CALL_TIMEOUT", "TOOL_CALL_ERROR"):
            if starts.get(tool_s, 0) <= 0:
                lifecycle_mismatch += 1
            else:
                starts[tool_s] -= 1

    lifecycle_mismatch += sum(v for v in starts.values() if v > 0)

    has_reply = any((r.payload_redacted or {}).get("event_type") == "REPLY" for r in records)
    has_timeout = any((r.payload_redacted or {}).get("event_type") == "TOOL_CALL_TIMEOUT" for r in records)
    has_error = any((r.payload_redacted or {}).get("event_type") == "TOOL_CALL_ERROR" for r in records)

    missing_failure_reply = 0
    if template_rules.require_reply_after_timeout and has_timeout and not has_reply:
        missing_failure_reply += 1
    if template_rules.require_reply_after_error and has_error and not has_reply:
        missing_failure_reply += 1

    # Penalties are coarse by design.
    score = 100
    if tool_missing:
        score = max(0, score - 50)
    if lifecycle_mismatch:
        score = max(0, score - 50)
    if missing_failure_reply:
        score = max(0, score - 50)
    return int(max(0, min(100, score)))


def _extract_perf_metrics(records: Sequence[ReplayTraceRecordV1]) -> tuple[int, int, int, int]:
    """Return (tool_calls, tool_latency_ms_total, llm_calls, llm_latency_ms_total)."""
    tool_calls = 0
    llm_calls = 0
    tool_lat = 0
    llm_lat = 0
    for r in records:
        p = r.payload_redacted or {}
        if not isinstance(p, dict):
            continue
        et = p.get("event_type")
        tool = p.get("tool")
        if not isinstance(et, str) or not isinstance(tool, str):
            continue
        is_llm = tool.startswith("llm.")
        if et == "TOOL_CALL_START":
            if is_llm:
                llm_calls += 1
            else:
                tool_calls += 1
        if et == "TOOL_CALL_DONE":
            try:
                ms = int(p.get("latency_ms") or 0)
            except Exception:
                ms = 0
            if is_llm:
                llm_lat += max(0, ms)
            else:
                tool_lat += max(0, ms)
    return tool_calls, tool_lat, llm_calls, llm_lat


def _latency_score(*, tool_latency_ms_total: int, llm_latency_ms_total: int) -> int:
    """Explainable stable score: 100 minus total latency / 50ms, clamped."""
    total = max(0, int(tool_latency_ms_total)) + max(0, int(llm_latency_ms_total))
    penalty = int(total // 50)
    return max(0, min(100, 100 - penalty))


def _cost_score(*, tool_calls: int, llm_calls: int) -> int:
    """Explainable stable score: per-call penalties (LLM costs more)."""
    tc = max(0, int(tool_calls))
    lc = max(0, int(llm_calls))
    penalty = 2 * tc + 10 * lc
    return max(0, min(100, 100 - penalty))


def load_assertions_pack(path: Path) -> list[tuple[int, TraceAssertion]]:
    """Load a JSON assertion pack: [{index: 0, assertion: {...}}, ...]."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("assertions pack must be a JSON array")
    out: list[tuple[int, TraceAssertion]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"assertions[{i}] must be an object")
        idx = item.get("index")
        mapping = item.get("assertion")
        if not isinstance(idx, int):
            raise ValueError(f"assertions[{i}].index must be an int")
        if not isinstance(mapping, dict):
            raise ValueError(f"assertions[{i}].assertion must be an object")
        out.append((idx, trace_assertion_from_mapping(mapping)))
    return out


def _normalize_assertion_indices(
    assertions: Sequence[tuple[int, TraceAssertion]], *, n_records: int
) -> list[tuple[int, TraceAssertion]]:
    out: list[tuple[int, TraceAssertion]] = []
    for idx, a in assertions:
        j = idx
        if j < 0:
            j = n_records + j
        out.append((j, a))
    return out


def _count_forbid_hits(
    records: Sequence[ReplayTraceRecordV1], forbid_strings: Iterable[str]
) -> int:
    needles = [str(x) for x in forbid_strings if str(x)]
    if not needles:
        return 0
    hits = 0
    for r in records:
        blob = r.model_dump_json()
        for s in needles:
            if s in blob:
                hits += 1
                break
    return hits


def _count_noise_hits(records: Sequence[ReplayTraceRecordV1]) -> int:
    # Heuristic UX/noise metric: detect "filler" replies in trace payloads.
    # This intentionally uses the same catalog-driven detector used by ports (log-only),
    # so we can regression-test "no meaningless quick reply" behavior in CI.
    from adami_kernel.i18n.ui_static import port_is_filler_reply_for_log

    hits = 0
    for r in records:
        payload = r.payload_redacted or {}
        text = payload.get("text")
        if isinstance(text, str) and port_is_filler_reply_for_log(text):
            hits += 1
    return hits


def evaluate_trace(
    *,
    records: Sequence[ReplayTraceRecordV1],
    assertions: Sequence[tuple[int, TraceAssertion]] = (),
    forbid_strings: Iterable[str] = (),
    scorecard: Optional[ScorecardSpec] = None,
    template_rules: Optional[TemplateRules] = None,
) -> EvalResult:
    failures: list[str] = []
    scorecard = scorecard or ScorecardSpec()
    template_rules = template_rules or TemplateRules()

    # Phase 1: schema + monotonic ts
    try:
        validate_phase1_records(records, allow_empty=False, monotonic_ts=True)
    except ReplayValidationError as e:
        failures.append(f"phase1_validation_failed: {e}")

    # Phase 2.1: assertions (topic/payload keys/forbid_string per assertion)
    if not failures and assertions:
        try:
            apply_assertions(records, _normalize_assertion_indices(assertions, n_records=len(records)))
        except AssertionError as e:
            failures.append(f"assertions_failed: {e}")

    duration_sec = 0.0
    if records:
        duration_sec = float(records[-1].ts - records[0].ts)

    # Global forbid strings (quick safety gate)
    n_forbid_hits = _count_forbid_hits(records, forbid_strings)
    if n_forbid_hits:
        failures.append(f"forbid_string_hit: hits={n_forbid_hits}")

    # UX/noise: filler reply detector
    n_noise_hits = _count_noise_hits(records)
    if n_noise_hits:
        failures.append(f"noise_filler_reply: hits={n_noise_hits}")

    tool_calls, tool_latency_ms_total, llm_calls, llm_latency_ms_total = _extract_perf_metrics(
        records
    )
    latency_score = _latency_score(
        tool_latency_ms_total=tool_latency_ms_total,
        llm_latency_ms_total=llm_latency_ms_total,
    )
    cost_score = _cost_score(tool_calls=tool_calls, llm_calls=llm_calls)

    # Template rule: tool timeout must be user-visible (have a REPLY somewhere).
    if template_rules.require_reply_after_timeout:
        has_timeout = any(
            isinstance((r.payload_redacted or {}).get("event_type"), str)
            and (r.payload_redacted or {}).get("event_type") == "TOOL_CALL_TIMEOUT"
            for r in records
        )
        if has_timeout:
            has_reply = any(
                isinstance((r.payload_redacted or {}).get("event_type"), str)
                and (r.payload_redacted or {}).get("event_type") == "REPLY"
                for r in records
            )
            if not has_reply:
                failures.append("tool_timeout_missing_reply")

    if template_rules.require_reply_after_error:
        has_err = any(
            isinstance((r.payload_redacted or {}).get("event_type"), str)
            and (r.payload_redacted or {}).get("event_type") == "TOOL_CALL_ERROR"
            for r in records
        )
        if has_err:
            has_reply = any(
                isinstance((r.payload_redacted or {}).get("event_type"), str)
                and (r.payload_redacted or {}).get("event_type") == "REPLY"
                for r in records
            )
            if not has_reply:
                failures.append("tool_error_missing_reply")

    if template_rules.require_tool_field_on_tool_calls:
        for i, r in enumerate(records):
            payload = r.payload_redacted or {}
            et = payload.get("event_type")
            if isinstance(et, str) and et.startswith("TOOL_CALL_"):
                if not payload.get("tool"):
                    failures.append(f"tool_call_missing_tool_field: record={i}")
                    break

    if template_rules.require_no_filler_reply:
        from adami_kernel.i18n.ui_static import port_is_filler_reply_for_log

        for i, r in enumerate(records):
            payload = r.payload_redacted or {}
            if payload.get("event_type") != "REPLY":
                continue
            text = payload.get("text")
            if isinstance(text, str) and port_is_filler_reply_for_log(text):
                failures.append(f"filler_reply_hard_gate: record={i}")
                break

    if template_rules.require_actionable_reply_on_tool_failure:
        keywords = tuple(x for x in template_rules.actionable_reply_keywords if str(x).strip())
        if keywords:
            has_failure = any(
                isinstance((r.payload_redacted or {}).get("event_type"), str)
                and (r.payload_redacted or {}).get("event_type") in ("TOOL_CALL_TIMEOUT", "TOOL_CALL_ERROR")
                for r in records
            )
            if has_failure:
                reply_texts: list[str] = []
                for r in records:
                    payload = r.payload_redacted or {}
                    if payload.get("event_type") != "REPLY":
                        continue
                    text = payload.get("text")
                    if isinstance(text, str) and text.strip():
                        reply_texts.append(text.strip())
                blob = "\n".join(reply_texts)

                def _kw_in_text(text: str, kw: str) -> bool:
                    if not kw:
                        return False
                    if kw.isascii():
                        return kw.lower() in text.lower()
                    return kw in text

                if not any(_kw_in_text(blob, kw) for kw in keywords):
                    failures.append("tool_failure_reply_not_actionable")

    # Dimension scores (0-100)
    correctness_score = 100 if not any(f.startswith(("phase1_", "assertions_")) for f in failures) else 0
    safety_score = max(0, 100 - min(100, 50 * n_forbid_hits))
    noise_score = max(0, 100 - min(100, 50 * n_noise_hits))
    operability_score = _operability_score(records=records, template_rules=template_rules)

    # UX: duration within budget + no filler. Simple but measurable.
    ux_score = 100
    if duration_sec > float(scorecard.max_duration_sec):
        ux_score = max(0, ux_score - 50)
    if n_noise_hits:
        ux_score = max(0, ux_score - 20 * n_noise_hits)

    w = scorecard.normalized_weights()
    score = int(
        round(
            w["correctness"] * correctness_score
            + w["safety"] * safety_score
            + w["ux"] * ux_score
            + w["noise"] * noise_score
            + w["operability"] * operability_score
            + w["latency"] * latency_score
            + w["cost"] * cost_score
        )
    )
    score = max(0, min(100, score))

    # Threshold gate
    threshold_failures: list[str] = []
    if correctness_score < scorecard.min_correctness:
        threshold_failures.append("threshold_correctness")
    if safety_score < scorecard.min_safety:
        threshold_failures.append("threshold_safety")
    if ux_score < scorecard.min_ux:
        threshold_failures.append("threshold_ux")
    if noise_score < scorecard.min_noise:
        threshold_failures.append("threshold_noise")
    if operability_score < scorecard.min_operability:
        threshold_failures.append("threshold_operability")
    if latency_score < scorecard.min_latency:
        threshold_failures.append("threshold_latency")
    if cost_score < scorecard.min_cost:
        threshold_failures.append("threshold_cost")
    if (
        scorecard.max_tool_latency_ms_total is not None
        and tool_latency_ms_total > int(scorecard.max_tool_latency_ms_total)
    ):
        threshold_failures.append("threshold_max_tool_latency_ms_total")
    if scorecard.max_llm_calls is not None and llm_calls > int(scorecard.max_llm_calls):
        threshold_failures.append("threshold_max_llm_calls")
    failures.extend(threshold_failures)

    ok = not failures

    return EvalResult(
        ok=ok,
        score=score,
        failures=tuple(failures),
        n_records=len(records),
        n_assertions=len(assertions),
        n_forbid_hits=n_forbid_hits,
        n_noise_hits=n_noise_hits,
        tool_calls=int(tool_calls),
        tool_latency_ms_total=int(tool_latency_ms_total),
        llm_calls=int(llm_calls),
        llm_latency_ms_total=int(llm_latency_ms_total),
        duration_sec=duration_sec,
        correctness_score=correctness_score,
        safety_score=safety_score,
        ux_score=ux_score,
        noise_score=noise_score,
        operability_score=int(operability_score),
        latency_score=int(latency_score),
        cost_score=int(cost_score),
    )


def evaluate_trace_file(
    *,
    trace_file: Path,
    assertions_file: Optional[Path] = None,
    forbid_strings: Iterable[str] = (),
    scorecard_file: Optional[Path] = None,
    template_scorecard_defaults: Optional[ScorecardSpec] = None,
    template_assertions_append: Sequence[tuple[int, TraceAssertion]] = (),
    template_rules: Optional[TemplateRules] = None,
) -> EvalResult:
    recs = load_ndjson_records(trace_file)
    assertions: Sequence[tuple[int, TraceAssertion]] = ()
    if assertions_file is not None:
        assertions = load_assertions_pack(assertions_file)
    if template_assertions_append:
        assertions = tuple(assertions) + tuple(template_assertions_append)
    spec: Optional[ScorecardSpec] = None
    if scorecard_file is not None and scorecard_file.is_file():
        spec = ScorecardSpec.from_path(scorecard_file)
    if template_scorecard_defaults is not None:
        spec = spec.merged_over(template_scorecard_defaults) if spec is not None else template_scorecard_defaults
    return evaluate_trace(
        records=recs,
        assertions=assertions,
        forbid_strings=forbid_strings,
        scorecard=spec,
        template_rules=template_rules,
    )


def _discover_suite_dirs(suite_dir: Path) -> list[Path]:
    if not suite_dir.is_dir():
        raise ValueError(f"suite_dir is not a directory: {suite_dir}")
    out: list[Path] = []
    for child in sorted(suite_dir.iterdir()):
        if not child.is_dir():
            continue
        if (child / "golden_trace.ndjson").is_file():
            out.append(child)
    return out


def _load_templates(*, suite_dir: Path) -> list[TemplateSpec]:
    td = suite_dir / "_templates"
    if not td.is_dir():
        return []
    out: list[TemplateSpec] = []
    for p in sorted(td.iterdir()):
        if p.is_file() and p.suffix.lower() == ".json":
            out.append(TemplateSpec.from_path(p))
    return out


def _template_applies(template: TemplateSpec, records: Sequence[ReplayTraceRecordV1]) -> bool:
    if template.applies_payload_event_type:
        for r in records:
            payload = r.payload_redacted or {}
            if payload.get("event_type") == template.applies_payload_event_type:
                return True
        return False
    if template.applies_payload_event_type_prefix:
        pref = template.applies_payload_event_type_prefix
        for r in records:
            payload = r.payload_redacted or {}
            et = payload.get("event_type")
            if isinstance(et, str) and et.startswith(pref):
                return True
        return False
    return False


def evaluate_suite_dir(*, suite_dir: Path, forbid_strings: Iterable[str] = ()) -> SuiteEvalResult:
    failures: list[str] = []
    traces: list[tuple[str, EvalResult]] = []

    templates = _load_templates(suite_dir=suite_dir)
    for sd in _discover_suite_dirs(suite_dir):
        name = sd.name
        trace_file = sd / "golden_trace.ndjson"
        assertions_file = sd / "assertions.json"
        scorecard_file = sd / "scorecard.json"
        # Pick templates by inspecting the trace first (small files; ok).
        recs = load_ndjson_records(trace_file)
        t_assertions: list[tuple[int, TraceAssertion]] = []
        t_scorecard: Optional[ScorecardSpec] = None
        t_rules = TemplateRules()
        for t in templates:
            if _template_applies(t, recs):
                if t.assertions_append:
                    t_assertions.extend(list(t.assertions_append))
                if t.scorecard_defaults is not None:
                    t_scorecard = (
                        t.scorecard_defaults.merged_over(t_scorecard)
                        if t_scorecard is not None
                        else t.scorecard_defaults
                    )
                # OR-merge rule flags across all applied templates.
                t_rules = TemplateRules(
                    require_reply_after_timeout=(
                        t_rules.require_reply_after_timeout or t.rules.require_reply_after_timeout
                    ),
                    require_reply_after_error=(
                        t_rules.require_reply_after_error or t.rules.require_reply_after_error
                    ),
                    require_no_filler_reply=(
                        t_rules.require_no_filler_reply or t.rules.require_no_filler_reply
                    ),
                    require_tool_field_on_tool_calls=(
                        t_rules.require_tool_field_on_tool_calls
                        or t.rules.require_tool_field_on_tool_calls
                    ),
                    require_actionable_reply_on_tool_failure=(
                        t_rules.require_actionable_reply_on_tool_failure
                        or t.rules.require_actionable_reply_on_tool_failure
                    ),
                    actionable_reply_keywords=tuple(
                        dict.fromkeys(
                            list(t_rules.actionable_reply_keywords) + list(t.rules.actionable_reply_keywords)
                        ).keys()
                    ),
                )
        res = evaluate_trace_file(
            trace_file=trace_file,
            assertions_file=assertions_file if assertions_file.is_file() else None,
            forbid_strings=forbid_strings,
            scorecard_file=scorecard_file if scorecard_file.is_file() else None,
            template_scorecard_defaults=t_scorecard,
            template_assertions_append=tuple(t_assertions),
            template_rules=t_rules,
        )
        traces.append((name, res))
        if not res.ok:
            failures.append(f"trace_failed:{name}")

    if not traces:
        failures.append("suite_empty:no_traces_found")

    avg = 0
    if traces:
        avg = int(round(sum(r.score for _, r in traces) / len(traces)))
    ok = not failures
    return SuiteEvalResult(ok=ok, score=avg, failures=tuple(failures), traces=tuple(traces))


def render_markdown_report(
    *,
    trace_file: Path,
    assertions_file: Optional[Path],
    forbid_strings: Sequence[str],
    result: EvalResult,
) -> str:
    lines: list[str] = []
    lines.append("## Replay eval report")
    lines.append("")
    lines.append(f"- trace: `{trace_file}`")
    lines.append(f"- assertions: `{assertions_file}`" if assertions_file else "- assertions: (none)")
    lines.append(f"- forbid_strings: {', '.join([f'`{x}`' for x in forbid_strings]) or '(none)'}")
    lines.append("")
    lines.append(f"### Result: {'PASS' if result.ok else 'FAIL'} (score={result.score})")
    lines.append("")
    lines.append(f"- n_records: {result.n_records}")
    lines.append(f"- n_assertions: {result.n_assertions}")
    lines.append(f"- n_forbid_hits: {result.n_forbid_hits}")
    lines.append(f"- n_noise_hits: {result.n_noise_hits}")
    lines.append(f"- tool_calls: {result.tool_calls}")
    lines.append(f"- tool_latency_ms_total: {result.tool_latency_ms_total}")
    lines.append(f"- llm_calls: {result.llm_calls}")
    lines.append(f"- llm_latency_ms_total: {result.llm_latency_ms_total}")
    lines.append(f"- duration_sec: {result.duration_sec:.3f}")
    lines.append("")
    lines.append("### Scorecard")
    lines.append(f"- correctness: {result.correctness_score}")
    lines.append(f"- safety: {result.safety_score}")
    lines.append(f"- ux: {result.ux_score}")
    lines.append(f"- noise: {result.noise_score}")
    lines.append(f"- operability: {result.operability_score}")
    lines.append(f"- latency: {result.latency_score}")
    lines.append(f"- cost: {result.cost_score}")
    if result.failures:
        lines.append("")
        lines.append("### Failures")
        for f in result.failures:
            lines.append(f"- {f}")
    lines.append("")
    return "\n".join(lines)


def render_suite_markdown_report(*, suite_dir: Path, forbid_strings: Sequence[str], result: SuiteEvalResult) -> str:
    lines: list[str] = []
    lines.append("## Replay eval suite report")
    lines.append("")
    lines.append(f"- suite_dir: `{suite_dir}`")
    lines.append(f"- forbid_strings: {', '.join([f'`{x}`' for x in forbid_strings]) or '(none)'}")
    lines.append("")
    lines.append(f"### Result: {'PASS' if result.ok else 'FAIL'} (score={result.score})")
    lines.append("")
    for name, r in result.traces:
        lines.append(f"#### Trace `{name}`: {'PASS' if r.ok else 'FAIL'} (score={r.score})")
        lines.append(f"- n_records: {r.n_records}")
        lines.append(f"- n_assertions: {r.n_assertions}")
        lines.append(f"- n_forbid_hits: {r.n_forbid_hits}")
        lines.append(f"- n_noise_hits: {r.n_noise_hits}")
        lines.append(f"- duration_sec: {r.duration_sec:.3f}")
        lines.append(f"- tool_calls: {r.tool_calls}")
        lines.append(f"- tool_latency_ms_total: {r.tool_latency_ms_total}")
        lines.append(f"- llm_calls: {r.llm_calls}")
        lines.append(f"- llm_latency_ms_total: {r.llm_latency_ms_total}")
        lines.append(f"- scorecard.correctness: {r.correctness_score}")
        lines.append(f"- scorecard.safety: {r.safety_score}")
        lines.append(f"- scorecard.ux: {r.ux_score}")
        lines.append(f"- scorecard.noise: {r.noise_score}")
        lines.append(f"- scorecard.operability: {r.operability_score}")
        lines.append(f"- scorecard.latency: {r.latency_score}")
        lines.append(f"- scorecard.cost: {r.cost_score}")
        if r.failures:
            for f in r.failures:
                lines.append(f"- failure: {f}")
        lines.append("")
    if result.failures:
        lines.append("### Suite failures")
        for f in result.failures:
            lines.append(f"- {f}")
        lines.append("")
    return "\n".join(lines)

