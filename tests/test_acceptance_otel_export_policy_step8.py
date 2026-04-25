"""
Step 8 acceptance: OTLP export — explicit trace sampling + export-time redaction.

Run:
  poetry run python -m pytest tests/test_acceptance_otel_export_policy_step8.py -q
"""

from __future__ import annotations

import json
from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_ac8_policy_module_documents_sampling_precedence() -> None:
    text = (_root() / "src" / "adami_kernel" / "observability" / "otel_export_policy.py").read_text(
        encoding="utf-8"
    )
    assert "resolve_trace_sampler" in text
    assert "RedactingSpanExporter" in text
    assert "ADAMI_OTEL_TRACES_SAMPLER" in text
    assert "OTEL_TRACES_SAMPLER" in text


def test_ac8_settings_exposes_otel_policy_fields() -> None:
    text = (_root() / "src" / "adami_kernel" / "config.py").read_text(encoding="utf-8")
    assert "ADAMI_OTEL_TRACES_SAMPLER" in text
    assert "ADAMI_OTEL_TRACES_SAMPLER_RATIO" in text
    assert "ADAMI_OTEL_EXPORT_REDACT_ENABLED" in text
    assert "ADAMI_OTEL_EXPORT_ATTR_VALUE_MAX_LEN" in text


def test_ac8_otel_py_wires_sampler_and_redacting_exporter() -> None:
    text = (_root() / "src" / "adami_kernel" / "web" / "otel.py").read_text(encoding="utf-8")
    assert "resolve_trace_sampler" in text
    assert "RedactingSpanExporter" in text
    assert "_trace_sampler_from_settings" in text
    assert "_register_batch_processor" in text
    assert "TracerProvider(sampler=" in text


def test_ac8_env_example_documents_sampling_and_redaction() -> None:
    text = (_root() / ".env.example").read_text(encoding="utf-8")
    assert "OTEL_TRACES_SAMPLER" in text
    assert "ADAMI_OTEL_TRACES_SAMPLER" in text
    assert "ADAMI_OTEL_EXPORT_REDACT" in text


def test_ac8_i18n_wbotel_trace_policy_locale_parity() -> None:
    for loc in ("en", "zh-Hans"):
        p = _root() / "src" / "adami_kernel" / "i18n" / "locales" / loc / "common.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data.get("wbotel.log.trace_sampler")
        assert data.get("wbotel.log.trace_export_redact")
        assert data.get("wbotel.debug.trace_policy_log_skip")
