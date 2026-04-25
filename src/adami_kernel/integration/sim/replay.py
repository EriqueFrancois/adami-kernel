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
    forbid_string: Optional[str] = None


def trace_assertion_from_mapping(raw: dict[str, Any]) -> TraceAssertion:
    """从 dict 构造（便于 YAML/JSON 黄金断言配置）。"""
    keys = raw.get("expect_payload_keys")
    fs = frozenset(keys) if keys is not None else None
    return TraceAssertion(
        expect_topic=raw.get("expect_topic"),
        expect_payload_keys=fs,
        forbid_string=raw.get("forbid_string"),
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
    """阶段 3 占位：故障注入（超时 / 异常 / DLQ）尚未接内核，仅保留扩展点。"""

    enabled: bool = False
    skip_indices: frozenset[int] = frozenset()


async def replay_inject_with_faults(
    records: Sequence[ReplayTraceRecordV1],
    inject: Callable[[AdamiEvent], Awaitable[None]],
    faults: FaultInjectionOptions,
) -> None:
    """阶段 3 占位：若 ``faults.enabled`` 且实现扩展，可跳过或抛错；当前与 ``replay_inject`` 等价。"""
    if not faults.enabled:
        await replay_inject(records, inject)
        return
    for i, rec in enumerate(records):
        if i in faults.skip_indices:
            continue
        await inject(record_to_adami_event(rec))
