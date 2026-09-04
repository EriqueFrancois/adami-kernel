from __future__ import annotations

import logging

import httpx
import pytest
from httpx import ASGITransport
from tests.demo.conftest import ORIGIN, auth_headers, open_session

from adami_kernel.demo.app import create_app
from adami_kernel.demo.redact import redact_text


def test_redact_strips_secrets_and_sid() -> None:
    text = redact_text("cookie adami_demo_sid=demo:abcDEF123456; ip 203.0.113.9 sk-abcdefghijklmnopqrstuvwxyz")
    assert "demo:abc" not in text
    assert "203.0.113.9" not in text
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in text


def test_metrics_loopback_ok(client) -> None:
    r = client.get("/v1/internal/metrics")
    assert r.status_code == 200
    body = r.json()
    assert "sessions" in body
    assert "cookie" not in str(body).lower()
    assert "adami_demo_sid" not in str(body)


@pytest.mark.asyncio
async def test_metrics_non_loopback_denied(demo_settings, runtime) -> None:
    app = create_app(settings=demo_settings, runtime=runtime)
    transport = ASGITransport(app=app, client=("203.0.113.50", 4444))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/v1/internal/metrics")
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_client_ip_header_only_from_loopback(demo_settings, runtime) -> None:
    runtime.limits.ip_per_minute = 1
    runtime.limits.ip_per_day = 1
    app = create_app(settings=demo_settings, runtime=runtime)
    loop_t = ASGITransport(app=app, client=("127.0.0.1", 9))
    pub_t = ASGITransport(app=app, client=("198.51.100.9", 9))
    headers = {
        "Origin": ORIGIN,
        "X-Adami-Client-IP": "8.8.8.8",
        "user-agent": "Mozilla/5.0",
    }
    async with httpx.AsyncClient(transport=loop_t, base_url="http://test") as ac:
        r1 = await ac.post("/v1/session", json={"locale": "en"}, headers=headers)
        assert r1.status_code == 200
        r2 = await ac.post("/v1/session", json={"locale": "en"}, headers=headers)
        assert r2.status_code == 429
    async with httpx.AsyncClient(transport=pub_t, base_url="http://test") as ac:
        # header must be ignored; uses `local` bucket, independent of the global IP above
        r3 = await ac.post("/v1/session", json={"locale": "en"}, headers=headers)
        assert r3.status_code == 200


def test_logs_do_not_echo_cookie(client, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    csrf = open_session(client)
    client.post(
        "/v1/turns",
        json={"scenarioId": "freeform", "message": "hello"},
        headers=auth_headers(csrf),
    )
    blob = caplog.text + str(caplog.records)
    assert "adami_demo_sid=" not in blob
    assert "sk-" not in blob


def test_restart_semantics(runtime, client) -> None:
    csrf = open_session(client)
    sid = client.cookies.get("adami_demo_sid")
    assert runtime.get_session(sid) is not None
    runtime.sessions.drop(sid)
    r = client.post(
        "/v1/turns",
        json={"scenarioId": "freeform", "message": "x"},
        headers=auth_headers(csrf),
    )
    assert r.status_code == 401
    assert r.json()["code"] == "session_expired"


def test_nginx_example_blocks_metrics() -> None:
    from pathlib import Path

    text = Path(__file__).resolve().parents[2].joinpath("deploy/nginx-adami-demo.conf.example").read_text()
    assert "internal/metrics" in text
    assert "return 404" in text
    assert "proxy_pass http://127.0.0.1:8091/" in text
    assert "client_max_body_size 8k" in text
    assert "proxy_buffering off" in text
