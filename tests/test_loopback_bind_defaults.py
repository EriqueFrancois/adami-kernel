"""Web Console and Health default to loopback bind."""

from __future__ import annotations

from adami_kernel.config import Settings


def test_web_and_health_bind_loopback_by_default() -> None:
    s = Settings()
    assert s.ADAMI_WEB_BIND_HOST == "127.0.0.1"
    assert s.ADAMI_HEALTH_BIND_HOST == "127.0.0.1"
    assert s.ADAMI_HEALTH_PORT == 8080
