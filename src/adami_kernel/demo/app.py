"""Localhost Guided Demo FastAPI application."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from adami_kernel.demo.config import DemoSettings, load_settings
from adami_kernel.demo.fallback import canned_fallback
from adami_kernel.demo.messages import error_message
from adami_kernel.demo.models import (
    SCENARIO_IDS,
    HealthBody,
    SessionCreateRequest,
    SessionCreateResponse,
    TurnRequest,
)
from adami_kernel.demo.scenarios import list_scenarios
from adami_kernel.demo.security import (
    CLIENT_IP_HEADER,
    COOKIE_NAME,
    CSRF_HEADER,
    classify_ua,
    identity_hash,
    is_loopback_host,
    origin_allowed,
    parse_globally_routable_ip,
    sec_fetch_site_ok,
    utc_date_today,
)
from adami_kernel.demo.tasks import DemoRuntime, iter_sse

logger = logging.getLogger("adami-demo")

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _peer_host(request: Request) -> str:
    client = request.client
    return (client.host if client else "") or ""


def _cookie_kwargs(settings: DemoSettings, max_age: int) -> dict[str, object]:
    return {
        "key": COOKIE_NAME,
        "httponly": True,
        "secure": bool(settings.COOKIE_SECURE),
        "samesite": "lax",
        "path": settings.COOKIE_PATH or "/api/demo/",
        "max_age": max_age,
    }


def _json_error(locale: str, code: str, status: int, *, with_fallback: bool = False, scenario: str = "freeform") -> JSONResponse:
    payload: dict[str, object] = {
        "code": code,
        "message": error_message(locale, code),
    }
    if with_fallback:
        payload["fallback"] = canned_fallback(locale, scenario, code).model_dump()
    return JSONResponse(payload, status_code=status)


def _check_origin(request: Request, settings: DemoSettings) -> str | None:
    origin = request.headers.get("origin")
    if not origin_allowed(origin, settings):
        return "origin_denied"
    if not sec_fetch_site_ok(request.headers.get("sec-fetch-site"), origin or ""):
        return "origin_denied"
    return None


def _identity(request: Request, settings: DemoSettings) -> str:
    peer = _peer_host(request)
    ip_token = "local"
    if is_loopback_host(peer):
        routed = parse_globally_routable_ip(request.headers.get(CLIENT_IP_HEADER))
        if routed:
            ip_token = routed
    ua = classify_ua(request.headers.get("user-agent"))
    return identity_hash(
        secret=settings.hmac_secret_bytes(),
        utc_date=utc_date_today(),
        ip_or_local=ip_token,
        ua_class=ua,
    )


def create_app(settings: DemoSettings | None = None, runtime: DemoRuntime | None = None) -> FastAPI:
    settings = settings or load_settings()
    runtime = runtime or DemoRuntime(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await runtime.startup()
        try:
            yield
        finally:
            await runtime.shutdown()

    app = FastAPI(title="Adami Guided Demo", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.settings = settings
    app.state.runtime = runtime
    origins = settings.allowed_origin_list()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", CSRF_HEADER, CLIENT_IP_HEADER],
        max_age=600,
    )

    @app.middleware("http")
    async def _count(request: Request, call_next):  # type: ignore[no-untyped-def]
        runtime.metrics.requests += 1
        return await call_next(request)

    def _session_from_cookie(request: Request):
        raw = request.cookies.get(COOKIE_NAME)
        if raw:
            raw = raw.strip().strip('"')
        return runtime.get_session(raw)

    @app.post("/v1/session")
    async def create_session(body: SessionCreateRequest, request: Request, response: Response):
        denied = _check_origin(request, settings)
        if denied:
            return _json_error("en", denied, 403)
        ident = _identity(request, settings)
        if not runtime.limits.allow_ip(ident):
            return _json_error(body.locale, "rate_limited", 429)
        sess, expires = runtime.create_session(body.locale)
        max_age = int(settings.SESSION_IDLE_TTL_SEC)
        response = JSONResponse(
            SessionCreateResponse(
                expiresAt=expires,
                turnsRemaining=settings.MAX_TURNS,
                maxTurns=settings.MAX_TURNS,
                csrfToken=sess.csrf_token,
                llmMode=settings.accepted_mode(),
            ).model_dump()
        )
        response.set_cookie(value=sess.session_id, **_cookie_kwargs(settings, max_age))  # type: ignore[arg-type]
        return response

    @app.get("/v1/scenarios")
    async def scenarios(request: Request):
        sess = _session_from_cookie(request)
        locale = sess.locale if sess else "en"
        return {"scenarios": [s.model_dump() for s in list_scenarios(locale)]}

    @app.get("/v1/fallback/{scenarioId}")
    async def fallback(scenarioId: str, request: Request):
        if scenarioId not in SCENARIO_IDS:
            return _json_error("en", "unavailable", 400)
        sess = _session_from_cookie(request)
        locale = sess.locale if sess else "en"
        return canned_fallback(locale, scenarioId, "unavailable").model_dump()

    @app.get("/v1/health")
    async def health() -> HealthBody:
        return HealthBody(status=runtime.health())  # type: ignore[arg-type]

    @app.get("/v1/internal/metrics")
    async def metrics(request: Request):
        if not is_loopback_host(_peer_host(request)):
            return JSONResponse({"code": "origin_denied", "message": "loopback only"}, status_code=403)
        return runtime.metrics.snapshot(
            sessions=runtime.sessions.count(),
            running=runtime._running,
            queued=len(runtime.wait_queue),
            rate_rejects=runtime.limits.rejects,
        )

    async def _require_write(request: Request):
        denied = _check_origin(request, settings)
        if denied:
            return None, _json_error("en", denied, 403)
        sess = _session_from_cookie(request)
        if sess is None:
            return None, _json_error("en", "session_expired", 401)
        csrf = request.headers.get(CSRF_HEADER)
        if not csrf or csrf != sess.csrf_token:
            return None, _json_error(sess.locale, "csrf_denied", 403)
        ident = _identity(request, settings)
        if not runtime.limits.allow_ip(ident) or not runtime.limits.allow_session(sess.session_id):
            return None, _json_error(sess.locale, "rate_limited", 429)
        return sess, None

    @app.post("/v1/turns")
    async def turns(body: TurnRequest, request: Request):
        sess, err = await _require_write(request)
        if err is not None:
            return err
        assert sess is not None
        runtime.metrics.requests += 0
        if len(body.message) > settings.MAX_INPUT_CHARS:
            return _json_error(sess.locale, "input_too_long", 400)
        if sess.turns_remaining(settings.MAX_TURNS) <= 0:
            return _json_error(sess.locale, "turn_limit", 403)
        active = [
            t
            for t in runtime.tasks.values()
            if t.session_id == sess.session_id and not t.finished.is_set()
        ]
        if sess.busy_task_id or active:
            existing = runtime.tasks.get(sess.busy_task_id or "") or (active[0] if active else None)
            if existing is not None and not existing.finished.is_set():
                if body.clientTurnId and sess.client_turn_ids.get(body.clientTurnId) == existing.task_id:
                    return StreamingResponse(
                        iter_sse(runtime, existing),
                        media_type="text/event-stream",
                        headers=SSE_HEADERS,
                    )
                return _json_error(sess.locale, "already_running", 409)
        if body.clientTurnId:
            prev = sess.client_turn_ids.get(body.clientTurnId)
            if prev and prev in runtime.tasks:
                return StreamingResponse(
                    iter_sse(runtime, runtime.tasks[prev]),
                    media_type="text/event-stream",
                    headers=SSE_HEADERS,
                )
        task = await runtime.start_turn(sess, body.scenarioId, body.message)
        if body.clientTurnId:
            sess.client_turn_ids[body.clientTurnId] = task.task_id
        return StreamingResponse(
            iter_sse(runtime, task),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )

    @app.post("/v1/turns/{taskId}/cancel")
    async def cancel(taskId: str, request: Request):
        sess, err = await _require_write(request)
        if err is not None:
            return err
        assert sess is not None
        task = runtime.tasks.get(taskId)
        if task is None or task.session_id != sess.session_id:
            return _json_error(sess.locale, "unavailable", 404)
        released = await runtime.cancel(task)
        return {"taskId": task.task_id, "released": released}

    @app.get("/v1/stream/{taskId}")
    async def stream(taskId: str, request: Request):
        denied = _check_origin(request, settings)
        if denied:
            return _json_error("en", denied, 403)
        sess = _session_from_cookie(request)
        if sess is None:
            return _json_error("en", "session_expired", 401)
        csrf = request.headers.get(CSRF_HEADER)
        if not csrf or csrf != sess.csrf_token:
            return _json_error(sess.locale, "csrf_denied", 403)
        task = runtime.tasks.get(taskId)
        if task is None or task.session_id != sess.session_id:
            return _json_error(sess.locale, "unavailable", 404)
        return StreamingResponse(
            iter_sse(runtime, task),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )

    return app
