"""验收：步骤 3（Sim Webhook 桥 + 自托管说明）。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEBHOOK = ROOT / "src" / "adami_kernel" / "integration" / "sim" / "webhook_client.py"
SMOKE = ROOT / "docs" / "sim_self_host_smoke.md"
CONFIG = ROOT / "src" / "adami_kernel" / "config.py"
PLAN = ROOT / "docs" / "sim_integration_plan.md"


def test_ac_sim_3_1_webhook_module_and_smoke_doc_exist() -> None:
    assert WEBHOOK.is_file()
    assert SMOKE.is_file()


def test_ac_sim_3_2_config_defines_webhook_settings() -> None:
    text = CONFIG.read_text(encoding="utf-8")
    for name in (
        "ADAMI_SIM_WEBHOOK_ENABLED",
        "ADAMI_SIM_WEBHOOK_URL",
        "ADAMI_SIM_WEBHOOK_SECRET",
        "ADAMI_SIM_WORKFLOW_ID",
        "ADAMI_SIM_WEBHOOK_MODE",
        "ADAMI_SIM_WEBHOOK_TIMEOUT_SEC",
    ):
        assert name in text


def test_ac_sim_3_3_trace_sink_calls_webhook() -> None:
    body = (ROOT / "src" / "adami_kernel" / "integration" / "sim" / "trace_sink.py").read_text(
        encoding="utf-8"
    )
    assert "post_sim_trace_webhook" in body


def test_ac_sim_3_4_plan_documents_step3() -> None:
    body = PLAN.read_text(encoding="utf-8")
    assert "webhook_client.py" in body or "步骤 3" in body
    assert "sim_self_host_smoke.md" in body


def test_ac_sim_3_5_integration_sim_exports_post_webhook() -> None:
    from adami_kernel.integration import sim as sim_pkg

    assert hasattr(sim_pkg, "post_sim_trace_webhook")


def test_ac_sim_3_6_env_example_mentions_webhook() -> None:
    ex = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "ADAMI_SIM_WEBHOOK" in ex


def test_ac_sim_3_7_smoke_doc_covers_curl_and_contract() -> None:
    t = SMOKE.read_text(encoding="utf-8")
    assert "curl" in t.lower()
    assert "adami_sim_webhook.batch.v1" in t or "batch.v1" in t
    assert "X-Adami-Signature" in t or "signature" in t.lower()
