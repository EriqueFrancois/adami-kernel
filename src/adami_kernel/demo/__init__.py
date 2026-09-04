"""Isolated Guided Demo HTTP service (localhost-only). Does not boot the kernel."""

__all__ = ["create_app"]


def create_app():
    from adami_kernel.demo.app import create_app as _create_app

    return _create_app()
