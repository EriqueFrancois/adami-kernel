"""Origin, CSRF, cookie, loopback, and client-identity helpers."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlparse

from adami_kernel.demo.config import DemoSettings

COOKIE_NAME = "adami_demo_sid"
CSRF_HEADER = "X-Adami-Demo-CSRF"
CLIENT_IP_HEADER = "X-Adami-Client-IP"

UAClass = Literal["browser", "mobile", "other"]


def new_session_id() -> str:
    return "demo:" + secrets.token_urlsafe(32)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)


def new_task_id() -> str:
    return "tsk_" + secrets.token_urlsafe(16)


def is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    h = host.split("%", 1)[0]
    if h in {"localhost", "127.0.0.1", "::1", "testclient"}:
        # Starlette TestClient uses "testclient"; treat as loopback for unit tests.
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def parse_globally_routable_ip(raw: str | None) -> str | None:
    if not raw:
        return None
    text = raw.strip()
    if not text or "," in text or " " in text:
        return None
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return None
    if addr.is_global:
        return str(addr)
    return None


def classify_ua(user_agent: str | None) -> UAClass:
    ua = (user_agent or "").lower()
    if any(x in ua for x in ("iphone", "android", "mobile", "ipad")):
        return "mobile"
    if any(x in ua for x in ("mozilla", "chrome", "safari", "firefox", "edg/")):
        return "browser"
    return "other"


def identity_hash(
    *,
    secret: bytes,
    utc_date: str,
    ip_or_local: str,
    ua_class: UAClass,
) -> str:
    msg = f"{utc_date}|{ip_or_local}|{ua_class}".encode("utf-8")
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()[:32]


def utc_date_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def origin_allowed(origin: str | None, settings: DemoSettings) -> bool:
    if not origin:
        return False
    got = origin.strip().rstrip("/")
    return got in settings.allowed_origin_list()


def origin_host_is_local_dev(origin: str) -> bool:
    try:
        host = (urlparse(origin).hostname or "").lower()
    except Exception:
        return False
    return host in {"localhost", "127.0.0.1", "::1"}


def sec_fetch_site_ok(sec_fetch_site: str | None, origin: str) -> bool:
    if not sec_fetch_site:
        return True
    site = sec_fetch_site.strip().lower()
    if site in {"same-origin", "none", "same-site"}:
        return True
    if site == "cross-site" and origin_host_is_local_dev(origin):
        return False
    return False
