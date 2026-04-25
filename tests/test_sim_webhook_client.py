"""步骤 3：Sim Webhook 桥（不启真实 Sim）。"""

from __future__ import annotations

import hashlib
import hmac
import json

import httpx
import pytest

import adami_kernel.config as config_mod
from adami_kernel.integration.sim import webhook_client as wc
from adami_kernel.integration.sim.schema import ReplayTraceRecordV1


def _sample_batch() -> list[ReplayTraceRecordV1]:
    return [
        ReplayTraceRecordV1(
            ts=1.0,
            trace_id="w1",
            source_module="m",
            target_topic="system.events",
            payload_redacted={"task": "x"},
        )
    ]


def test_build_envelope_includes_workflow_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_WEBHOOK_MODE", "envelope")
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_WORKFLOW_ID", "wf-demo")
    batch = _sample_batch()
    body, hdr = wc._build_body_and_headers(batch, batch[0].to_ndjson_line())
    assert hdr["Content-Type"].startswith("application/json")
    obj = json.loads(body.decode("utf-8"))
    assert obj["schema"] == wc.WEBHOOK_SCHEMA_V1
    assert obj["workflow_id"] == "wf-demo"
    assert len(obj["records"]) == 1


def test_build_ndjson_raw_matches_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_WEBHOOK_MODE", "ndjson_raw")
    batch = _sample_batch()
    nd = batch[0].to_ndjson_line()
    body, hdr = wc._build_body_and_headers(batch, nd)
    assert body.decode("utf-8") == nd
    assert "ndjson" in hdr["Content-Type"]


def test_hmac_header_matches_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_WEBHOOK_MODE", "envelope")
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_WEBHOOK_SECRET", "s3cr3t")
    batch = _sample_batch()
    body, hdr = wc._build_body_and_headers(batch, "")
    signed = wc._sign_headers(body, hdr)
    assert "X-Adami-Signature" in signed
    hex_part = signed["X-Adami-Signature"].removeprefix("sha256=")
    expect = hmac.new(b"s3cr3t", body, hashlib.sha256).hexdigest()
    assert hex_part == expect


@pytest.mark.asyncio
async def test_post_sim_webhook_no_raise_on_network_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_MODULE_ENABLED", True)
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_WEBHOOK_ENABLED", True)
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_WEBHOOK_URL", "http://127.0.0.1:9/nope")
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_WEBHOOK_TIMEOUT_SEC", 0.1)

    async def boom(*_a, **_kw):
        raise httpx.ConnectError("sim unreachable", request=None)

    monkeypatch.setattr(httpx.AsyncClient, "post", boom)

    batch = _sample_batch()
    client = httpx.AsyncClient()
    try:
        await wc.post_sim_trace_webhook(client, batch, batch[0].to_ndjson_line())
    finally:
        await client.aclose()

    assert any("SimWebhook" in r.name and "failed" in r.message.lower() for r in caplog.records)


@pytest.mark.asyncio
async def test_post_sim_webhook_warns_on_http_500(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_MODULE_ENABLED", True)
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_WEBHOOK_ENABLED", True)
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_WEBHOOK_URL", "http://example.invalid/sim")

    async def fake_post(self, url, content=None, headers=None, timeout=None, **kw):
        return httpx.Response(500, text="fail", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    batch = _sample_batch()
    client = httpx.AsyncClient()
    try:
        await wc.post_sim_trace_webhook(client, batch, batch[0].to_ndjson_line())
    finally:
        await client.aclose()

    assert any("500" in r.message for r in caplog.records)
