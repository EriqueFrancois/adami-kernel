"""Sim 数据桥：将轨迹批次 POST 到自托管 Webhook（可选 HMAC）；失败只打 warning，不抛到内核热路径。"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Sequence

import httpx

import adami_kernel.config as config_mod
from adami_kernel.integration.sim.schema import ReplayTraceRecordV1

logger = logging.getLogger("AdamI-SimWebhook")

WEBHOOK_SCHEMA_V1 = "adami_sim_webhook.batch.v1"


def _webhook_enabled() -> bool:
    s = config_mod.settings
    return config_mod.sim_module_master_enabled(s) and bool(
        getattr(s, "ADAMI_SIM_WEBHOOK_ENABLED", False)
    )


def _build_body_and_headers(
    batch: Sequence[ReplayTraceRecordV1],
    ndjson_text: str,
) -> tuple[bytes, dict[str, str]]:
    s = config_mod.settings
    mode = (getattr(s, "ADAMI_SIM_WEBHOOK_MODE", "envelope") or "envelope").strip().lower()
    if mode == "ndjson_raw":
        body = ndjson_text.encode("utf-8")
        headers = {"Content-Type": "application/x-ndjson"}
        return body, headers

    payload: dict = {
        "source": "adami-kernel",
        "schema": WEBHOOK_SCHEMA_V1,
        "records": [r.model_dump(mode="json") for r in batch],
    }
    wf = getattr(s, "ADAMI_SIM_WORKFLOW_ID", None)
    if wf and str(wf).strip():
        payload["workflow_id"] = str(wf).strip()
    body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    return body_bytes, headers


def _sign_headers(body: bytes, base_headers: dict[str, str]) -> dict[str, str]:
    secret = (getattr(config_mod.settings, "ADAMI_SIM_WEBHOOK_SECRET", None) or "").strip()
    if not secret:
        return base_headers
    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    out = dict(base_headers)
    out["X-Adami-Signature"] = f"sha256={sig}"
    return out


async def post_sim_trace_webhook(
    client: httpx.AsyncClient,
    batch: Sequence[ReplayTraceRecordV1],
    ndjson_text: str,
) -> None:
    """在 trace flush 后调用；网络错误或非 2xx 仅 ``warning``，不抛。"""
    if not _webhook_enabled():
        return
    url = (getattr(config_mod.settings, "ADAMI_SIM_WEBHOOK_URL", None) or "").strip()
    if not url:
        logger.debug("[SimWebhook] enabled but ADAMI_SIM_WEBHOOK_URL empty; skip")
        return
    timeout = float(getattr(config_mod.settings, "ADAMI_SIM_WEBHOOK_TIMEOUT_SEC", 5.0) or 5.0)
    try:
        body, hdr = _build_body_and_headers(batch, ndjson_text)
        hdr = _sign_headers(body, hdr)
        resp = await client.post(url, content=body, headers=hdr, timeout=timeout)
        if resp.status_code >= 400:
            logger.warning(
                "[SimWebhook] HTTP %s (ignored): %s",
                resp.status_code,
                (resp.text or "")[:300],
            )
    except Exception as e:
        logger.warning("[SimWebhook] POST failed (ignored): %s", e)
