from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from adami_kernel.demo.app import create_app
from adami_kernel.demo.config import load_settings
from adami_kernel.demo.llm.fake import FakeLLM
from adami_kernel.demo.tasks import DemoRuntime

ORIGIN = "http://localhost:4321"


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def demo_settings() -> object:
    return load_settings(
        COOKIE_SECURE=False,
        COOKIE_PATH="/",
        ALLOWED_ORIGINS=ORIGIN,
        LLM_PROVIDER="fake",
        SESSION_CLEANUP_SEC=0.05,
        RATE_IP_PER_MINUTE=1000,
        RATE_IP_PER_DAY=10000,
        RATE_SESSION_PER_MINUTE=1000,
        DISCONNECT_GRACE_SEC=0.2,
        TERMINAL_RETAIN_SEC=0.4,
        WAIT_TIMEOUT_SEC=45.0,
        TASK_TIMEOUT_SEC=2.0,
    )


@pytest.fixture
def runtime(demo_settings: object, fake_llm: FakeLLM) -> DemoRuntime:
    return DemoRuntime(demo_settings, llm=fake_llm)  # type: ignore[arg-type]


@pytest.fixture
def client(demo_settings: object, runtime: DemoRuntime) -> Iterator[TestClient]:
    app = create_app(settings=demo_settings, runtime=runtime)  # type: ignore[arg-type]
    with TestClient(app) as c:
        yield c


def auth_headers(csrf: str) -> dict[str, str]:
    return {"Origin": ORIGIN, "X-Adami-Demo-CSRF": csrf}


def open_session(client: TestClient, locale: str = "en") -> str:
    r = client.post("/v1/session", json={"locale": locale}, headers={"Origin": ORIGIN})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "sessionId" not in body
    assert "csrfToken" in body
    return str(body["csrfToken"])


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    name = None
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        ev = None
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                ev = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].strip())
        if ev and data_lines:
            events.append((ev, json.loads("\n".join(data_lines))))
            name = ev
    _ = name
    return events
