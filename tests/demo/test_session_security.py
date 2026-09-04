from __future__ import annotations

import ast
from pathlib import Path

from tests.demo.conftest import ORIGIN, auth_headers, open_session, parse_sse

from adami_kernel.demo.cli import main
from adami_kernel.demo.models import SCENARIO_IDS


def test_session_json_has_no_session_id(client) -> None:
    r = client.post("/v1/session", json={"locale": "en"}, headers={"Origin": ORIGIN})
    assert r.status_code == 200
    body = r.json()
    assert "sessionId" not in body
    assert "session_id" not in body
    assert set(body) == {"expiresAt", "turnsRemaining", "maxTurns", "csrfToken", "llmMode", "disclaimer"}
    cookie = r.cookies.get("adami_demo_sid")
    assert cookie and cookie.startswith("demo:")
    assert body["llmMode"] == "fake"
    assert body["disclaimer"] == "capability-demo"


def test_cookie_secure_false_local(client) -> None:
    r = client.post("/v1/session", json={"locale": "zh-CN"}, headers={"Origin": ORIGIN})
    header = r.headers.get("set-cookie", "")
    assert "adami_demo_sid=" in header
    assert "HttpOnly" in header
    assert "SameSite=lax" in header or "SameSite=Lax" in header
    assert "Secure" not in header


def test_origin_denied(client) -> None:
    r = client.post("/v1/session", json={"locale": "en"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert r.json()["code"] == "origin_denied"


def test_csrf_denied(client) -> None:
    open_session(client)
    r = client.post(
        "/v1/turns",
        json={"scenarioId": "freeform", "message": "hi"},
        headers={"Origin": ORIGIN, "X-Adami-Demo-CSRF": "nope"},
    )
    assert r.status_code == 403
    assert r.json()["code"] == "csrf_denied"


def test_ignores_x_forwarded_for(runtime, client) -> None:
    csrf = open_session(client)
    runtime.limits._ip_min.clear()
    runtime.limits._ip_day.clear()
    runtime.limits.ip_per_minute = 1
    runtime.limits.ip_per_day = 40
    h = auth_headers(csrf)
    h["X-Forwarded-For"] = "8.8.8.8"
    r = client.post("/v1/turns", json={"scenarioId": "freeform", "message": "a"}, headers=h)
    assert r.status_code == 200
    r2 = client.post("/v1/turns", json={"scenarioId": "freeform", "message": "b"}, headers=h)
    assert r2.status_code == 429
    assert r2.json()["code"] == "rate_limited"


def test_scenarios_enum_bilingual(client) -> None:
    csrf = open_session(client, "zh-CN")
    r = client.get("/v1/scenarios", headers=auth_headers(csrf))
    ids = [s["id"] for s in r.json()["scenarios"]]
    assert ids == list(SCENARIO_IDS)
    assert any("Demo" in s["disclaimer"] or "交互层" in s["disclaimer"] for s in r.json()["scenarios"])
    en = client.post("/v1/session", json={"locale": "en"}, headers={"Origin": ORIGIN})
    client.cookies.set("adami_demo_sid", en.cookies["adami_demo_sid"])
    r2 = client.get("/v1/scenarios")
    assert r2.json()["scenarios"][0]["id"] == "what-adami-can-do"


def test_fallback_canned_not_live(client) -> None:
    r = client.get("/v1/fallback/goal-planning")
    body = r.json()
    assert body["label"] == "canned-demo"
    assert "live" not in body
    assert body["scenarioId"] == "goal-planning"


def test_health_limited_fields(client) -> None:
    r = client.get("/v1/health")
    assert r.json()["status"] in {"ok", "degraded", "unavailable"}
    assert "api" not in r.text.lower() or "key" not in r.json()
    assert "ADAMI_DATA" not in r.text


def test_cli_rejects_non_loopback() -> None:
    assert main(["--host", "0.0.0.0", "--port", "8091", "--workers", "1"]) == 2
    assert main(["--host", "127.0.0.1", "--workers", "2"]) == 2


def test_demo_package_does_not_import_kernel_runtime() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "adami_kernel" / "demo"
    forbidden = (
        "adami_kernel.cortex.decision_processor",
        "adami_kernel.cortex.tools_manager",
        "adami_kernel.cortex.router",
        "adami_kernel.kernel",
        "adami_kernel.core",
        "adami_kernel.hippocampus",
        "adami_kernel.telemetry.experience_sink",
        "adami_kernel.web.app",
        "adami_kernel.nexus.health_server",
        "adami_kernel.nexus.bus",
    )
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module not in forbidden, path
                assert not node.module.startswith("adami_kernel.core")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in forbidden


def test_openapi_lists_error_codes() -> None:
    text = Path(__file__).resolve().parents[2].joinpath("docs/demo/openapi.yaml").read_text()
    for code in (
        "rate_limited",
        "turn_limit",
        "csrf_denied",
        "origin_denied",
        "tool_denied",
        "queue_full",
    ):
        assert code in text
    assert "sessionId" not in text.split("SessionCreateResponse")[1].split("TurnRequest")[0]
    assert "live" in text and "fake" in text
    assert "chunked-complete" in text


def test_happy_path_sse_fake_not_live(client) -> None:
    csrf = open_session(client)
    r = client.post(
        "/v1/turns",
        json={"scenarioId": "what-adami-can-do", "message": "hello"},
        headers=auth_headers(csrf),
    )
    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")
    events = parse_sse(r.text)
    names = [n for n, _ in events]
    assert "accepted" in names
    acc = next(p for n, p in events if n == "accepted")
    assert acc["mode"] == "fake"
    assert acc["streaming"] == "chunked-complete"
    assert "done" in names
    assert "delta" in names
