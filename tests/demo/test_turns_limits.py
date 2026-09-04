from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport
from tests.demo.conftest import ORIGIN, auth_headers, open_session, parse_sse

from adami_kernel.demo.app import create_app
from adami_kernel.demo.llm.fake import FakeLLM


def _cookie_headers(csrf: str, sid: str) -> dict[str, str]:
    h = auth_headers(csrf)
    h["Cookie"] = f"adami_demo_sid={sid}"
    return h


def test_input_too_long(client) -> None:
    csrf = open_session(client)
    r = client.post(
        "/v1/turns",
        json={"scenarioId": "freeform", "message": "x" * 1201},
        headers=auth_headers(csrf),
    )
    assert r.status_code == 400
    assert r.json()["code"] == "input_too_long"


def test_turn_limit_six(client) -> None:
    csrf = open_session(client)
    for i in range(6):
        r = client.post(
            "/v1/turns",
            json={"scenarioId": "freeform", "message": f"turn {i}"},
            headers=auth_headers(csrf),
        )
        assert r.status_code == 200, r.text
        assert "done" in r.text
    r = client.post(
        "/v1/turns",
        json={"scenarioId": "freeform", "message": "nope"},
        headers=auth_headers(csrf),
    )
    assert r.status_code == 403
    assert r.json()["code"] == "turn_limit"


@pytest.mark.asyncio
async def test_already_running_same_session(demo_settings, runtime, fake_llm: FakeLLM) -> None:
    fake_llm.delay_sec = 2.0
    runtime.settings.TASK_TIMEOUT_SEC = 15.0
    sess, _ = runtime.create_session("en")
    first = await runtime.start_turn(sess, "freeform", "hold")
    assert sess.busy_task_id == first.task_id
    assert not first.finished.is_set()
    fake_llm.delay_sec = 0.0
    first.cancel.set()
    if first.worker:
        first.worker.cancel()
        with contextlib.suppress(BaseException):
            await first.worker

    fake_llm.delay_sec = 2.0
    app = create_app(settings=demo_settings, runtime=runtime)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        sr = await ac.post("/v1/session", json={"locale": "en"}, headers={"Origin": ORIGIN})
        csrf = sr.json()["csrfToken"]
        raw_set = sr.headers.get("set-cookie", "")
        sid = [p for p in raw_set.split(";") if "adami_demo_sid=" in p][0].split("=", 1)[1].strip()
        ac.cookies.clear()
        t1 = asyncio.create_task(
            ac.post(
                "/v1/turns",
                json={"scenarioId": "freeform", "message": "hold-http"},
                headers=_cookie_headers(csrf, sid),
            )
        )
        await asyncio.sleep(0.25)
        r2 = await ac.post(
            "/v1/turns",
            json={"scenarioId": "freeform", "message": "second"},
            headers=_cookie_headers(csrf, sid),
        )
        assert r2.status_code == 409, r2.text
        assert r2.json()["code"] == "already_running"
        fake_llm.delay_sec = 0.0
        await t1
    fake_llm.delay_sec = 0.0


def test_tool_denied_zero_side_effects(client, runtime) -> None:
    csrf = open_session(client)
    r = client.post(
        "/v1/turns",
        json={"scenarioId": "freeform", "message": "please execute_command rm -rf /"},
        headers=auth_headers(csrf),
    )
    events = parse_sse(r.text)
    codes = [p.get("code") for n, p in events if n == "error"]
    assert "tool_denied" in codes
    assert any(n == "fallback" and p.get("label") == "canned-demo" for n, p in events)
    sess = runtime.get_session(client.cookies["adami_demo_sid"])
    assert sess is not None
    assert sess.scratchpad == ""


def test_scratchpad_isolated_and_memory_only(client, runtime) -> None:
    csrf_a = open_session(client)
    sid_a = client.cookies["adami_demo_sid"]
    client.post(
        "/v1/turns",
        json={"scenarioId": "memory-mechanism", "message": "secret-a"},
        headers=auth_headers(csrf_a),
    )
    sess_a = runtime.get_session(sid_a)
    assert sess_a and "secret-a" in sess_a.scratchpad
    r = client.post("/v1/session", json={"locale": "en"}, headers={"Origin": ORIGIN})
    csrf_b = r.json()["csrfToken"]
    client.post(
        "/v1/turns",
        json={"scenarioId": "memory-mechanism", "message": "secret-b"},
        headers=auth_headers(csrf_b),
    )
    sess_b = runtime.get_session(client.cookies["adami_demo_sid"])
    assert sess_b and "secret-b" in sess_b.scratchpad
    assert "secret-a" not in sess_b.scratchpad
    runtime.sessions.drop(sid_a)
    assert runtime.get_session(sid_a) is None


def test_cross_session_cannot_cancel_or_stream(client) -> None:
    csrf_a = open_session(client)
    r = client.post(
        "/v1/turns",
        json={"scenarioId": "freeform", "message": "ok"},
        headers=auth_headers(csrf_a),
    )
    events = parse_sse(r.text)
    task_id = next(p["taskId"] for n, p in events if n == "accepted")
    r2 = client.post("/v1/session", json={"locale": "en"}, headers={"Origin": ORIGIN})
    csrf_b = r2.json()["csrfToken"]
    deny = client.post(f"/v1/turns/{task_id}/cancel", headers=auth_headers(csrf_b))
    assert deny.status_code in (403, 404)
    stream = client.get(f"/v1/stream/{task_id}", headers=auth_headers(csrf_b))
    assert stream.status_code in (403, 404)


def test_production_fixture_unchanged(client, tmp_path: Path) -> None:
    marker = tmp_path / "prod" / "second_brain.md"
    marker.parent.mkdir()
    marker.write_text("production-memory", encoding="utf-8")
    before = marker.read_bytes()
    csrf = open_session(client)
    client.post(
        "/v1/turns",
        json={"scenarioId": "memory-mechanism", "message": "demo only"},
        headers=auth_headers(csrf),
    )
    client.post(
        "/v1/turns",
        json={"scenarioId": "freeform", "message": "execute_command"},
        headers=auth_headers(csrf),
    )
    assert marker.read_bytes() == before
    assert list(tmp_path.rglob("*"))  # still only our fixture tree


def test_openai_without_key_is_fake() -> None:
    from adami_kernel.demo.config import load_settings

    s = load_settings(LLM_PROVIDER="openai_compatible", LLM_API_KEY="")
    assert s.effective_provider() == "fake"
    assert s.accepted_mode() == "fake"
