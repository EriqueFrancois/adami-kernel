#!/usr/bin/env python3
"""Thin wrapper; implementation lives in ``adami_kernel.ops.ops_boot_self_check_cli``."""
from __future__ import annotations

from adami_kernel.ops.ops_boot_self_check_cli import main

if __name__ == "__main__":
    raise SystemExit(main())
