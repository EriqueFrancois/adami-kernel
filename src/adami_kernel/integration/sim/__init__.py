"""模块三（Sim）集成层：轨迹契约与 EventBus 导出。"""

from adami_kernel.integration.sim.mcp_bridge import SIM_MCP_BRIDGE_DOC, SimMcpBridgePath
from adami_kernel.integration.sim.replay import (
    FaultInjectionOptions,
    ReplayValidationError,
    TraceAssertion,
    apply_assertions,
    assert_record_matches,
    load_ndjson_records,
    record_to_adami_event,
    replay_inject,
    replay_inject_with_faults,
    trace_assertion_from_mapping,
    validate_phase1_records,
)
from adami_kernel.integration.sim.schema import (
    TRACE_SCHEMA_V1,
    ReplayTraceRecordV1,
)
from adami_kernel.integration.sim.trace_sink import (
    EventBusTraceSink,
    event_to_record,
    get_trace_sink,
    offer_trace_event_for_system_path,
    reset_sim_trace_sink_for_tests,
)
from adami_kernel.integration.sim.webhook_client import post_sim_trace_webhook

__all__ = [
    "TRACE_SCHEMA_V1",
    "ReplayTraceRecordV1",
    "EventBusTraceSink",
    "event_to_record",
    "get_trace_sink",
    "offer_trace_event_for_system_path",
    "reset_sim_trace_sink_for_tests",
    "ReplayValidationError",
    "TraceAssertion",
    "trace_assertion_from_mapping",
    "assert_record_matches",
    "apply_assertions",
    "load_ndjson_records",
    "validate_phase1_records",
    "record_to_adami_event",
    "replay_inject",
    "FaultInjectionOptions",
    "replay_inject_with_faults",
    "post_sim_trace_webhook",
    "SIM_MCP_BRIDGE_DOC",
    "SimMcpBridgePath",
]
