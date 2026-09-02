from __future__ import annotations

import json
from pathlib import Path


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_suite_templates_apply_tool_timeout_rules(tmp_path: Path) -> None:
    # Build a minimal suite dir with a template and a tool-timeout trace without REPLY.
    suite = tmp_path
    tmpl_dir = suite / "_templates"
    _write(
        tmpl_dir / "tool_timeout.json",
        json.dumps(
            {
                "name": "tool_timeout",
                "applies_when": {"payload_event_type": "TOOL_CALL_TIMEOUT"},
                "rules": {"require_reply_after_timeout": True},
                "assertions_append": [
                    {"index": 1, "assertion": {"expect_payload_keys": ["event_type", "tool", "timeout_sec"]}}
                ],
                "scorecard_defaults": {"min_ux": 90},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )

    sd = suite / "tool_timeout"
    _write(
        sd / "golden_trace.ndjson",
        "\n".join(
            [
                json.dumps(
                    {
                        "schema_version": "adami_replay_trace.v1",
                        "ts": 1.0,
                        "trace_id": "t1",
                        "episode_id": None,
                        "source_module": "toolbox.execute_command",
                        "target_topic": "system.events",
                        "event_type": "adami_event",
                        "payload_redacted": {"event_type": "TOOL_CALL_START", "tool": "execute_command", "timeout_sec": 0.1},
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "schema_version": "adami_replay_trace.v1",
                        "ts": 2.0,
                        "trace_id": "t1",
                        "episode_id": None,
                        "source_module": "toolbox.execute_command",
                        "target_topic": "system.events",
                        "event_type": "adami_event",
                        "payload_redacted": {"event_type": "TOOL_CALL_TIMEOUT", "tool": "execute_command", "timeout_sec": 0.1},
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
    )
    _write(sd / "assertions.json", "[]\n")

    from adami_kernel.integration.sim.replay_eval import evaluate_suite_dir

    res = evaluate_suite_dir(suite_dir=suite, forbid_strings=())
    assert not res.ok
    # Template rule must fail it.
    assert any("trace_failed:tool_timeout" == f for f in res.failures)


def test_scorecard_template_defaults_and_trace_override(tmp_path: Path) -> None:
    # Template default min_ux=90 but trace overrides to 95.
    suite = tmp_path
    _write(
        suite / "_templates" / "tool_timeout.json",
        json.dumps(
            {
                "name": "tool_timeout",
                "applies_when": {"payload_event_type": "TOOL_CALL_TIMEOUT"},
                "scorecard_defaults": {"min_ux": 90, "max_duration_sec": 1.0},
            },
            ensure_ascii=False,
        )
        + "\n",
    )
    sd = suite / "tool_timeout"
    _write(
        sd / "golden_trace.ndjson",
        "\n".join(
            [
                json.dumps(
                    {
                        "schema_version": "adami_replay_trace.v1",
                        "ts": 1.0,
                        "trace_id": "t1",
                        "episode_id": None,
                        "source_module": "toolbox.execute_command",
                        "target_topic": "system.events",
                        "event_type": "adami_event",
                        "payload_redacted": {"event_type": "TOOL_CALL_TIMEOUT", "tool": "execute_command", "timeout_sec": 0.1},
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "schema_version": "adami_replay_trace.v1",
                        "ts": 5.0,
                        "trace_id": "t1",
                        "episode_id": None,
                        "source_module": "nexus.reply",
                        "target_topic": "system.events",
                        "event_type": "adami_event",
                        "payload_redacted": {"event_type": "REPLY", "text": "ok", "trace_id": "t1"},
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
    )
    _write(sd / "assertions.json", "[]\n")
    _write(sd / "scorecard.json", json.dumps({"min_ux": 95}, ensure_ascii=False) + "\n")

    from adami_kernel.integration.sim.replay_eval import evaluate_suite_dir

    res = evaluate_suite_dir(suite_dir=suite, forbid_strings=())
    assert not res.ok
    # With duration 4s and max_duration 1s, ux_score will drop, so threshold_ux should appear.
    assert any("trace_failed:tool_timeout" == f for f in res.failures)


def test_tool_call_common_template_prefix_applies(tmp_path: Path) -> None:
    # Prefix applies to any TOOL_CALL_* record; require tool field.
    suite = tmp_path
    _write(
        suite / "_templates" / "tool_call_common.json",
        json.dumps(
            {
                "name": "tool_call_common",
                "applies_when": {"payload_event_type_prefix": "TOOL_CALL_"},
                "rules": {"require_tool_field_on_tool_calls": True},
            },
            ensure_ascii=False,
        )
        + "\n",
    )
    sd = suite / "x"
    _write(
        sd / "golden_trace.ndjson",
        json.dumps(
            {
                "schema_version": "adami_replay_trace.v1",
                "ts": 1.0,
                "trace_id": "t1",
                "episode_id": None,
                "source_module": "toolbox.execute_command",
                "target_topic": "system.events",
                "event_type": "adami_event",
                "payload_redacted": {"event_type": "TOOL_CALL_TIMEOUT", "timeout_sec": 0.1},
            },
            ensure_ascii=False,
        )
        + "\n",
    )
    _write(sd / "assertions.json", "[]\n")

    from adami_kernel.integration.sim.replay_eval import evaluate_suite_dir

    res = evaluate_suite_dir(suite_dir=suite, forbid_strings=())
    assert not res.ok


def test_tool_failure_reply_actionable_keywords_gate(tmp_path: Path) -> None:
    suite = tmp_path
    _write(
        suite / "_templates" / "tool_call_reply_actionable.json",
        json.dumps(
            {
                "name": "tool_call_reply_actionable",
                "applies_when": {"payload_event_type_prefix": "TOOL_CALL_"},
                "rules": {"require_actionable_reply_on_tool_failure": True},
                "actionable_reply_keywords": ["retry", "reduce scope"],
            },
            ensure_ascii=False,
        )
        + "\n",
    )
    sd = suite / "t"
    _write(
        sd / "golden_trace.ndjson",
        "\n".join(
            [
                json.dumps(
                    {
                        "schema_version": "adami_replay_trace.v1",
                        "ts": 1.0,
                        "trace_id": "t1",
                        "episode_id": None,
                        "source_module": "toolbox.execute_command",
                        "target_topic": "system.events",
                        "event_type": "adami_event",
                        "payload_redacted": {"event_type": "TOOL_CALL_TIMEOUT", "tool": "execute_command", "timeout_sec": 0.1},
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "schema_version": "adami_replay_trace.v1",
                        "ts": 2.0,
                        "trace_id": "t1",
                        "episode_id": None,
                        "source_module": "nexus.reply",
                        "target_topic": "system.events",
                        "event_type": "adami_event",
                        "payload_redacted": {"event_type": "REPLY", "text": "Please try again.", "trace_id": "t1"},
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
    )
    _write(sd / "assertions.json", "[]\n")

    from adami_kernel.integration.sim.replay_eval import evaluate_suite_dir

    res = evaluate_suite_dir(suite_dir=suite, forbid_strings=())
    assert not res.ok

