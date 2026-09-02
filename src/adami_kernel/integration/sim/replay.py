"""步骤 2：离线回放骨架 — 阶段 1 校验、阶段 2 mock inject、断言 DSL；阶段 3 故障注入占位。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, List, Optional, Sequence, Union

from adami_kernel.integration.sim.schema import TRACE_SCHEMA_V1, ReplayTraceRecordV1
from adami_kernel.nexus.event import AdamiEvent, EventPriority

logger = logging.getLogger("AdamI-SimReplay")

PathLike = Union[str, Path]


class ReplayValidationError(ValueError):
    """NDJSON 或契约校验失败。"""


@dataclass
class TraceAssertion:
    """2.1 断言模型（可组合）。"""

    expect_topic: Optional[str] = None
    expect_payload_keys: Optional[frozenset[str]] = None
    # Payload subset match on a specific record.
    expect_payload: Optional[dict[str, Any]] = None
    forbid_string: Optional[str] = None
    # "Anywhere" assertions (scan all records; index is ignored).
    expect_payload_anywhere: Optional[dict[str, Any]] = None
    forbid_payload_anywhere: Optional[dict[str, Any]] = None


def trace_assertion_from_mapping(raw: dict[str, Any]) -> TraceAssertion:
    """从 dict 构造（便于 YAML/JSON 黄金断言配置）。"""
    keys = raw.get("expect_payload_keys")
    fs = frozenset(keys) if keys is not None else None
    return TraceAssertion(
        expect_topic=raw.get("expect_topic"),
        expect_payload=raw.get("expect_payload") if isinstance(raw.get("expect_payload"), dict) else None,
        expect_payload_keys=fs,
        forbid_string=raw.get("forbid_string"),
        expect_payload_anywhere=raw.get("expect_payload_anywhere") if isinstance(raw.get("expect_payload_anywhere"), dict) else None,
        forbid_payload_anywhere=raw.get("forbid_payload_anywhere") if isinstance(raw.get("forbid_payload_anywhere"), dict) else None,
    )


def load_ndjson_records(path: PathLike) -> List[ReplayTraceRecordV1]:
    """读取 NDJSON，每行一条 ``ReplayTraceRecordV1``。"""
    p = Path(path)
    if not p.is_file():
        raise ReplayValidationError(f"trace file not found: {p}")
    out: List[ReplayTraceRecordV1] = []
    text = p.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            out.append(ReplayTraceRecordV1.model_validate(obj))
        except (json.JSONDecodeError, ValueError) as e:
            raise ReplayValidationError(f"line {lineno}: invalid JSON or schema: {e}") from e
    return out


def validate_phase1_records(
    records: Sequence[ReplayTraceRecordV1],
    *,
    allow_empty: bool = False,
    monotonic_ts: bool = True,
) -> None:
    """阶段 1：契约与顺序（时间非递减）。"""
    if not records:
        if allow_empty:
            return
        raise ReplayValidationError("trace contains no records")
    prev_ts: Optional[float] = None
    for i, r in enumerate(records):
        if r.schema_version != TRACE_SCHEMA_V1:
            raise ReplayValidationError(
                f"record {i}: schema_version expected {TRACE_SCHEMA_V1!r}, got {r.schema_version!r}"
            )
        if not str(r.trace_id).strip():
            raise ReplayValidationError(f"record {i}: trace_id empty")
        if not str(r.source_module).strip():
            raise ReplayValidationError(f"record {i}: source_module empty")
        if not str(r.target_topic).strip():
            raise ReplayValidationError(f"record {i}: target_topic empty")
        if monotonic_ts:
            if prev_ts is not None and r.ts < prev_ts:
                raise ReplayValidationError(
                    f"record {i}: ts {r.ts} < previous {prev_ts} (monotonic_ts violated)"
                )
            prev_ts = r.ts


def assert_record_matches(record: ReplayTraceRecordV1, assertion: TraceAssertion) -> None:
    """对单条记录跑断言；失败抛 ``AssertionError``。"""
    if assertion.expect_topic is not None:
        assert (
            record.target_topic == assertion.expect_topic
        ), f"topic: expected {assertion.expect_topic!r}, got {record.target_topic!r}"
    if assertion.expect_payload is not None:
        payload = record.payload_redacted or {}
        missing = []
        mismatched = []
        for k, v in assertion.expect_payload.items():
            if k not in payload:
                missing.append(str(k))
                continue
            if payload.get(k) != v:
                mismatched.append((str(k), payload.get(k), v))
        assert not missing, f"payload_redacted missing keys: {sorted(missing)}"
        assert not mismatched, f"payload_redacted mismatched: {mismatched!r}"
    if assertion.expect_payload_keys:
        missing = assertion.expect_payload_keys - frozenset(record.payload_redacted.keys())
        assert not missing, f"payload_redacted missing keys: {sorted(missing)}"
    if assertion.forbid_string:
        blob = record.model_dump_json()
        assert (
            assertion.forbid_string not in blob
        ), f"forbid_string {assertion.forbid_string!r} found in record json"


def apply_assertions(
    records: Sequence[ReplayTraceRecordV1],
    assertions: Sequence[tuple[int, TraceAssertion]],
) -> None:
    """按 (索引, 断言) 列表校验；索引越界抛 ``AssertionError``。"""
    for idx, ass in assertions:
        if ass.expect_payload_anywhere is not None:
            found = False
            for r in records:
                payload = r.payload_redacted or {}
                ok = True
                for k, v in ass.expect_payload_anywhere.items():
                    if payload.get(k) != v:
                        ok = False
                        break
                if ok:
                    found = True
                    break
            assert found, f"expect_payload_anywhere not found: {ass.expect_payload_anywhere!r}"
            continue
        if ass.forbid_payload_anywhere is not None:
            forbid = ass.forbid_payload_anywhere
            hit = False
            for r in records:
                payload = r.payload_redacted or {}
                ok = True
                for k, v in forbid.items():
                    if payload.get(k) != v:
                        ok = False
                        break
                if ok:
                    hit = True
                    break
            assert not hit, f"forbid_payload_anywhere matched: {forbid!r}"
            continue

        assert 0 <= idx < len(records), f"assertion index {idx} out of range (len={len(records)})"
        assert_record_matches(records[idx], ass)


def record_to_adami_event(
    record: ReplayTraceRecordV1, priority: EventPriority = EventPriority.NORMAL
) -> AdamiEvent:
    """阶段 2：将轨迹行还原为 ``AdamiEvent``（优先级默认 NORMAL，因 v1 未持久化 priority）。"""
    return AdamiEvent(
        trace_id=record.trace_id,
        source_module=record.source_module,
        target_topic=record.target_topic,
        priority=priority,
        payload=dict(record.payload_redacted),
    )


async def replay_inject(
    records: Sequence[ReplayTraceRecordV1],
    inject: Callable[[AdamiEvent], Awaitable[None]],
) -> None:
    """阶段 2：按序 inject，不经过真实 EventBus（便于 mock LLM/MCP 的测试夹具）。"""
    for rec in records:
        await inject(record_to_adami_event(rec))


@dataclass
class FaultInjectionOptions:
    """阶段 3：故障注入（用于验证回放/评估门禁的鲁棒性）。

    This operates at the **inject** layer (record -> AdamiEvent). It is deterministic and
    intentionally minimal: skipping, raising, and payload mutation are enough to simulate
    common regressions (event drops, malformed payloads, and hard failures).
    """

    enabled: bool = False
    skip_indices: frozenset[int] = frozenset()
    raise_indices: Optional[dict[int, str]] = None  # index -> message
    replace_payload_at: Optional[dict[int, dict[str, Any]]] = None  # index -> payload dict update

    @staticmethod
    def from_mapping(raw: dict[str, Any]) -> "FaultInjectionOptions":
        if not isinstance(raw, dict):
            raise ValueError("fault injection config must be an object")
        skip = raw.get("skip_indices") or []
        if not isinstance(skip, list):
            raise ValueError("skip_indices must be a list[int]")
        raise_map = raw.get("raise_indices") or {}
        if not isinstance(raise_map, dict):
            raise ValueError("raise_indices must be an object {index: message}")
        rep = raw.get("replace_payload_at") or {}
        if not isinstance(rep, dict):
            raise ValueError("replace_payload_at must be an object {index: payload_update_object}")

        def _int_keys(m: dict[str, Any]) -> dict[int, Any]:
            out: dict[int, Any] = {}
            for k, v in m.items():
                try:
                    ik = int(k)
                except Exception as e:
                    raise ValueError(f"fault injection index must be int-like, got {k!r}") from e
                out[ik] = v
            return out

        rep2: dict[int, dict[str, Any]] = {}
        for ik, v in _int_keys(rep).items():
            if not isinstance(v, dict):
                raise ValueError(f"replace_payload_at[{ik}] must be an object")
            rep2[int(ik)] = {str(k): v2 for k, v2 in v.items()}

        raise2: dict[int, str] = {int(k): str(v) for k, v in _int_keys(raise_map).items()}
        skip2 = frozenset(int(x) for x in skip)
        return FaultInjectionOptions(
            enabled=bool(raw.get("enabled", True)),
            skip_indices=skip2,
            raise_indices=raise2,
            replace_payload_at=rep2,
        )


def load_fault_injection_options(path: PathLike) -> FaultInjectionOptions:
    p = Path(path)
    raw = json.loads(p.read_text(encoding="utf-8"))
    return FaultInjectionOptions.from_mapping(raw)


async def replay_inject_with_faults(
    records: Sequence[ReplayTraceRecordV1],
    inject: Callable[[AdamiEvent], Awaitable[None]],
    faults: FaultInjectionOptions,
) -> None:
    """阶段 3：按规则执行故障注入。"""
    if not faults.enabled:
        await replay_inject(records, inject)
        return
    for i, rec in enumerate(records):
        if i in faults.skip_indices:
            continue
        if faults.raise_indices and i in faults.raise_indices:
            raise ReplayValidationError(f"fault_injection_raise: index={i}: {faults.raise_indices[i]}")
        if faults.replace_payload_at and i in faults.replace_payload_at:
            patched = dict(rec.payload_redacted or {})
            patched.update(dict(faults.replace_payload_at[i] or {}))
            rec = rec.model_copy(update={"payload_redacted": patched})
        await inject(record_to_adami_event(rec))


def apply_faults_to_records(
    records: Sequence[ReplayTraceRecordV1],
    faults: FaultInjectionOptions,
) -> list[ReplayTraceRecordV1]:
    """Apply phase-3 faults directly to a record sequence (pure, deterministic)."""
    if not faults.enabled:
        return list(records)
    out: list[ReplayTraceRecordV1] = []
    for i, rec in enumerate(records):
        if i in faults.skip_indices:
            continue
        if faults.raise_indices and i in faults.raise_indices:
            raise ReplayValidationError(f"fault_injection_raise: index={i}: {faults.raise_indices[i]}")
        if faults.replace_payload_at and i in faults.replace_payload_at:
            patched = dict(rec.payload_redacted or {})
            patched.update(dict(faults.replace_payload_at[i] or {}))
            rec = rec.model_copy(update={"payload_redacted": patched})
        out.append(rec)
    return out
