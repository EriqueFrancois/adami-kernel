#!/usr/bin/env python3
"""仓库根目录入口：转发到包内 CLI（便于 ``poetry run python scripts/replay_trace.py``）。"""
from adami_kernel.integration.sim.replay_cli import main

if __name__ == "__main__":
    raise SystemExit(main())
