from __future__ import annotations

from tests.demo.conftest import ORIGIN, auth_headers, open_session, parse_sse

from adami_kernel.demo.sse import format_sse
from adami_kernel.demo.tasks import DemoRuntime


def test_ring_caps_at_32kib(runtime: DemoRuntime) -> None:
    from adami_kernel.demo.tasks import DemoTask

    task = DemoTask(task_id="t", session_id="s", scenario_id="freeform", message="m", locale="en", mode="fake")
    runtime.settings.RING_MAX_BYTES = 32768
    chunk = format_sse("delta", {"text": "x" * 200})
    for _ in range(400):
        runtime._append_ring(task, chunk)
    assert len(task.ring) <= 32768


def test_reconnect_same_session(client, runtime) -> None:
    csrf = open_session(client)
    r = client.post(
        "/v1/turns",
        json={"scenarioId": "freeform", "message": "ok"},
        headers=auth_headers(csrf),
    )
    events = parse_sse(r.text)
    task_id = next(p["taskId"] for n, p in events if n == "accepted")
    r2 = client.get(f"/v1/stream/{task_id}", headers=auth_headers(csrf))
    assert r2.status_code == 200
    replay = parse_sse(r2.text)
    assert any(n == "done" for n, _ in replay)

    other = client.post("/v1/session", json={"locale": "en"}, headers={"Origin": ORIGIN})
    csrf_b = other.json()["csrfToken"]
    r3 = client.get(f"/v1/stream/{task_id}", headers=auth_headers(csrf_b))
    assert r3.status_code in (403, 404)
