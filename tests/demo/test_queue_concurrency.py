from __future__ import annotations

import asyncio

import httpx
import pytest
from httpx import ASGITransport
from tests.demo.conftest import ORIGIN, auth_headers, parse_sse

from adami_kernel.demo.app import create_app
from adami_kernel.demo.llm.fake import FakeLLM


def _headers(csrf: str, sid: str) -> dict[str, str]:
    h = auth_headers(csrf)
    h["Cookie"] = f"adami_demo_sid={sid}"
    return h


async def _session(ac: httpx.AsyncClient, locale: str = "en") -> tuple[str, str]:
    r = await ac.post("/v1/session", json={"locale": locale}, headers={"Origin": ORIGIN})
    assert r.status_code == 200, r.text
    sid = r.cookies.get("adami_demo_sid")
    if not sid:
        raw = r.headers.get("set-cookie", "")
        if "adami_demo_sid=" in raw:
            sid = raw.split("adami_demo_sid=", 1)[1].split(";", 1)[0]
    assert sid
    return str(r.json()["csrfToken"]), str(sid)


@pytest.mark.asyncio
async def test_global_concurrency_two_and_third_queues(demo_settings, runtime, fake_llm: FakeLLM) -> None:
    fake_llm.block = asyncio.Event()
    app = create_app(settings=demo_settings, runtime=runtime)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        sessions = []
        for _ in range(3):
            sessions.append(await _session(ac))

        async def start(i: int) -> httpx.Response:
            csrf, sid = sessions[i]
            return await ac.post(
                "/v1/turns",
                json={"scenarioId": "freeform", "message": f"m{i}"},
                headers=_headers(csrf, sid),
            )

        t0 = asyncio.create_task(start(0))
        t1 = asyncio.create_task(start(1))
        await asyncio.sleep(0.15)
        assert runtime._running == 2
        t2 = asyncio.create_task(start(2))
        await asyncio.sleep(0.15)
        assert len(runtime.wait_queue) == 1
        fake_llm.block.set()
        r0, r1, r2 = await asyncio.gather(t0, t1, t2)
        assert all(x.status_code == 200 for x in (r0, r1, r2))
        queued = parse_sse(r2.text)
        assert any(n == "queued" for n, _ in queued)
        pos = next(p["position"] for n, p in queued if n == "queued")
        assert pos == 1


@pytest.mark.asyncio
async def test_queue_full_returns_canned(demo_settings, runtime, fake_llm: FakeLLM) -> None:
    fake_llm.block = asyncio.Event()
    demo_settings.QUEUE_MAX = 2  # type: ignore[attr-defined]
    runtime.wait_queue.maxsize = 2
    app = create_app(settings=demo_settings, runtime=runtime)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        cookies = []
        for _ in range(5):
            cookies.append(await _session(ac))

        async def start(i: int) -> httpx.Response:
            csrf, sid = cookies[i]
            return await ac.post(
                "/v1/turns",
                json={"scenarioId": "goal-planning", "message": f"q{i}"},
                headers=_headers(csrf, sid),
            )

        tasks = [asyncio.create_task(start(i)) for i in range(4)]
        await asyncio.sleep(0.2)
        extra = await start(4)
        assert extra.status_code == 200
        events = parse_sse(extra.text)
        assert any(n == "error" and p.get("code") == "queue_full" for n, p in events)
        assert any(n == "fallback" and p.get("label") == "canned-demo" for n, p in events)
        fake_llm.block.set()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_wait_timeout_releases_queue(demo_settings, runtime, fake_llm: FakeLLM) -> None:
    fake_llm.block = asyncio.Event()
    demo_settings.WAIT_TIMEOUT_SEC = 0.15  # type: ignore[attr-defined]
    runtime.settings.WAIT_TIMEOUT_SEC = 0.15
    app = create_app(settings=demo_settings, runtime=runtime)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        held = []
        for _ in range(3):
            held.append(await _session(ac))

        async def start(i: int) -> httpx.Response:
            csrf, sid = held[i]
            return await ac.post(
                "/v1/turns",
                json={"scenarioId": "freeform", "message": f"w{i}"},
                headers=_headers(csrf, sid),
            )

        t0 = asyncio.create_task(start(0))
        t1 = asyncio.create_task(start(1))
        await asyncio.sleep(0.05)
        t2 = asyncio.create_task(start(2))
        r2 = await t2
        events = parse_sse(r2.text)
        assert any(n == "error" and p.get("code") == "wait_timeout" for n, p in events)
        assert any(n == "fallback" for n, p in events)
        assert len(runtime.wait_queue) == 0
        fake_llm.block.set()
        await asyncio.gather(t0, t1)


@pytest.mark.asyncio
async def test_task_timeout_releases_slot(demo_settings, runtime, fake_llm: FakeLLM) -> None:
    fake_llm.block = asyncio.Event()
    runtime.settings.TASK_TIMEOUT_SEC = 0.15
    app = create_app(settings=demo_settings, runtime=runtime)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        csrf, _sid = await _session(ac)
        r = await ac.post(
            "/v1/turns",
            json={"scenarioId": "freeform", "message": "slow"},
            headers=_headers(csrf, _sid),
        )
        events = parse_sse(r.text)
        assert any(n == "error" for n, p in events)
        assert any(n == "fallback" for n, p in events)
        assert runtime._running == 0
        fake_llm.block.set()


@pytest.mark.asyncio
async def test_cancel_queue_and_slot(demo_settings, runtime, fake_llm: FakeLLM) -> None:
    fake_llm.block = asyncio.Event()
    app = create_app(settings=demo_settings, runtime=runtime)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        pairs = []
        for _ in range(3):
            pairs.append(await _session(ac))

        async def start(i: int):
            csrf, sid = pairs[i]
            async with ac.stream(
                "POST",
                "/v1/turns",
                json={"scenarioId": "freeform", "message": f"c{i}"},
                headers=_headers(csrf, sid),
            ) as resp:
                buf = b""
                async for chunk in resp.aiter_bytes():
                    buf += chunk
                    if b"event: queued" in buf or b"event: accepted" in buf:
                        return buf, csrf, sid
                return buf, csrf, sid

        t0 = asyncio.create_task(start(0))
        t1 = asyncio.create_task(start(1))
        await asyncio.sleep(0.1)
        t2 = asyncio.create_task(start(2))
        buf2, csrf2, sid2 = await t2
        events = parse_sse(buf2.decode("utf-8", errors="replace"))
        qid = next(p["taskId"] for n, p in events if n in {"queued", "accepted"})
        cr = await ac.post(f"/v1/turns/{qid}/cancel", headers=_headers(csrf2, sid2))
        assert cr.status_code == 200
        assert cr.json()["released"] in {"queue", "slot"}
        fake_llm.block.set()
        await asyncio.gather(t0, t1, return_exceptions=True)


@pytest.mark.asyncio
async def test_disconnect_grace_cancels(demo_settings, runtime, fake_llm: FakeLLM) -> None:
    fake_llm.block = asyncio.Event()
    runtime.settings.DISCONNECT_GRACE_SEC = 0.15
    app = create_app(settings=demo_settings, runtime=runtime)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        csrf, sid = await _session(ac)
        async with ac.stream(
            "POST",
            "/v1/turns",
            json={"scenarioId": "freeform", "message": "hold"},
            headers=_headers(csrf, sid),
        ) as resp:
            async for _ in resp.aiter_bytes():
                break
        await asyncio.sleep(0.35)
        assert runtime._running == 0
        fake_llm.block.set()
