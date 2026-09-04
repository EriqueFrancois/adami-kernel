"""Server-controlled LLM endpoint checks. Clients cannot supply a base URL."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

_BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata.internal",
}


def assert_safe_llm_base_url(
    url: str,
    *,
    allow_http: bool = False,
    allowed_hosts: list[str] | None = None,
) -> str:
    raw = (url or "").strip()
    if not raw:
        raise ValueError("LLM base URL is empty")
    parsed = urlparse(raw)
    if parsed.scheme == "https":
        pass
    elif parsed.scheme == "http" and allow_http:
        pass
    else:
        raise ValueError("LLM base URL must use https")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise ValueError("LLM base URL is missing a host")
    if parsed.username or parsed.password:
        raise ValueError("LLM base URL must not include credentials")
    if host in _BLOCKED_HOSTS or host.endswith(".local") or host.endswith(".internal"):
        raise ValueError("LLM base URL host is not allowed")
    try:
        addr = ipaddress.ip_address(host)
        if not addr.is_global:
            raise ValueError("LLM base URL must not target private or loopback addresses")
    except ValueError as exc:
        if "must not" in str(exc) or "not allowed" in str(exc):
            raise
        # hostname, not a literal IP
        pass
    if allowed_hosts:
        allow = {h.strip().lower() for h in allowed_hosts if h.strip()}
        if host not in allow:
            raise ValueError("LLM base URL host is not on the allowlist")
    return raw.rstrip("/")
