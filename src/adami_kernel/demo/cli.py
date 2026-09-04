"""CLI: ``adami-demo`` — single-worker localhost Guided Demo API."""

from __future__ import annotations

import argparse
import ipaddress
import logging
import sys


def _is_loopback(host: str) -> bool:
    if host in {"127.0.0.1", "localhost", "::1"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Adami Guided Demo API (localhost only).")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    from adami_kernel.demo.app import create_app
    from adami_kernel.demo.config import load_settings

    settings = load_settings()
    host = args.host or settings.HOST
    port = int(args.port or settings.PORT)
    workers = int(args.workers if args.workers is not None else settings.WORKERS)
    if workers != 1:
        print(
            "adami-demo v1 uses in-memory sessions/queue; workers must be 1.",
            file=sys.stderr,
        )
        return 2
    if not _is_loopback(host):
        print(
            f"Refusing to bind {host}: Guided Demo must listen on loopback (127.0.0.1).",
            file=sys.stderr,
        )
        if not settings.ALLOW_NON_LOOPBACK:
            return 2
        print("ADAMI_DEMO_ALLOW_NON_LOOPBACK is set; continuing with warning.", file=sys.stderr)
    if settings.COOKIE_SECURE and not str(settings.COOKIE_SECRET or "").strip():
        print(
            "ADAMI_DEMO_COOKIE_SECURE is true but ADAMI_DEMO_COOKIE_SECRET is empty. "
            "Refusing to start with the built-in development cookie secret.",
            file=sys.stderr,
        )
        return 2
    if settings.LLM_PROVIDER == "openai_compatible" and settings.effective_provider() != "openai_compatible":
        print(
            "ADAMI_DEMO_LLM_PROVIDER=openai_compatible is set but live mode is not enabled "
            "(missing key/model, host allowlist, or base URL failed safety checks). Refusing to start.",
            file=sys.stderr,
        )
        return 2

    import uvicorn

    app = create_app(settings=settings)
    uvicorn.run(app, host=host, port=port, workers=1, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
