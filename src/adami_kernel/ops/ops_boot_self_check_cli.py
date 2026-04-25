"""Console entry: ``adami-ops-boot-check`` (see pyproject ``[tool.poetry.scripts]``)."""

from __future__ import annotations

import argparse
import json
import sys


def _print_human(report: object) -> None:
    from adami_kernel.ops.boot_self_check import BootSelfCheckReport

    assert isinstance(report, BootSelfCheckReport)
    lines: list[str] = []
    lines.append("AdamI ops boot self-check")
    lines.append("=" * 48)
    dkr = report.docker_daemon_reachable
    dkr_s = {True: "yes", False: "no", None: "unknown"}.get(dkr, "unknown")
    lines.append(f"Runtime profile:        {report.runtime_profile}")
    lines.append(f"Container (/.dockerenv): {report.in_container_auto}")
    lines.append(f"DEBUG:                  {report.debug}")
    lines.append(f"Docker daemon ping:     {dkr_s}")
    lines.append("")
    lines.append("Enabled modules / features:")
    for m in report.modules_enabled:
        lines.append(f"  + {m}")
    if report.modules_notable_off:
        lines.append("")
        lines.append("Notable off (subset):")
        for m in report.modules_notable_off:
            lines.append(f"  - {m}")
    lines.append("")
    lines.append("Warnings / blockers:")
    if not report.warnings:
        lines.append("  (none)")
    else:
        for w in report.warnings:
            lines.append(f"  {w}")
    lines.append("")
    lines.append("Exit hint: fix [BLOCKER] before expecting nerve bootstrap to succeed.")
    lines.append("Exit codes: 0 = clean, 1 = WARN only, 2 = BLOCKER (or WARN+BLOCKER).")
    sys.stdout.write("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="AdamI ops boot self-check (read-only).")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a single JSON object on stdout.",
    )
    args = parser.parse_args()

    # Re-read .env / cli_overrides so ops exports apply without importing the kernel first.
    from adami_kernel.config import reload_settings

    reload_settings()

    from adami_kernel.ops.boot_self_check import run_boot_self_check

    report = run_boot_self_check()
    if args.json:
        sys.stdout.write(json.dumps(report.to_json_dict(), ensure_ascii=False) + "\n")
    else:
        _print_human(report)

    if any(str(x).startswith("[BLOCKER]") for x in report.warnings):
        return 2
    if any(str(x).startswith("[WARN]") for x in report.warnings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
