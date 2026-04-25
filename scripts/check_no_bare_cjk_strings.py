#!/usr/bin/env python3
"""Step 7：扫描 A 类路径中的「裸」中文字符串字面量（渐进式门禁）。

规则（概要）
-----------
- 使用 AST 识别 ``str`` / ``f-string`` 中的 CJK；**注释**不在 AST 中，天然忽略。
- 跳过：模块/类/函数的 **docstring**；``logging.*`` / ``logger.*`` / ``*.logger.*`` 等常见日志调用实参子树。
- 行尾 ``# adami:allow-cjk`` 跳过该行上的字面量命中。
- ``path_segment_whitelist``：相对路径任一段命中则跳过整文件（便于日志/观测目录）。
- ``legacy_file_allowlist``：仅 **warn**（默认仍 exit 0）；其它文件中的命中为 **error**（exit 1）。

环境变量
--------
- ``ADAMI_I18N_CJK_GATE=error``（默认）：非豁免文件出现命中即失败；豁免文件仅打印警告。
- ``ADAMI_I18N_CJK_GATE=warn``：全部命中仅警告，exit 0（渐进接入 CI 时可短暂使用）。
- ``ADAMI_I18N_CJK_GATE_VERBOSE=1`` 或 ``--verbose``：打印 legacy 文件中的逐条命中（默认仅汇总）。

更新豁免清单（把当前违规文件写入 JSON）::

  python scripts/check_no_bare_cjk_strings.py --write-allowlist

``scan_globs`` 可用 ``**/*.py`` 或 ``./**/*.py`` 表示 ``kernel_root`` 下全部 ``*.py``（等价 rglob）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from ast_user_visible_literals import collect_literal_hits  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path(__file__).resolve().parent / "i18n_cjk_gate.json"


@dataclass(frozen=True)
class Hit:
    path: Path
    lineno: int
    col_offset: int
    snippet: str
    legacy: bool


def _load_config(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if int(data.get("version", 1)) != 1:
        raise SystemExit(f"Unsupported config version in {path}")
    return data


def _kernel_root(cfg: dict[str, Any]) -> Path:
    rel = str(cfg.get("kernel_root") or "src/adami_kernel").strip().strip("/")
    return (REPO_ROOT / rel).resolve()


def _iter_scan_files(kernel_root: Path, globs: Sequence[str]) -> list[Path]:
    out: set[Path] = set()
    for pat in globs:
        pat = pat.strip().lstrip("/")
        # Whole-kernel shortcut (same as ``./**/*.py`` under ``kernel_root``).
        if pat in ("**/*.py", "./**/*.py"):
            for p in kernel_root.rglob("*.py"):
                if p.is_file():
                    out.add(p.resolve())
            continue
        if "**" in pat:
            if "/**/" not in pat:
                raise SystemExit(f"Invalid glob (need /**/ segment): {pat!r}")
            base, rest = pat.split("/**/", 1)
            start = kernel_root / base
            if not start.is_dir():
                continue
            for p in start.rglob(rest):
                if p.is_file() and p.suffix == ".py":
                    out.add(p.resolve())
        else:
            p = (kernel_root / pat).resolve()
            if p.is_file():
                out.add(p)
    return sorted(out)


def _path_whitelisted(rel_posix: str, segments: Sequence[str]) -> bool:
    parts = rel_posix.split("/")
    for seg in segments:
        if seg and seg in parts:
            return True
    return False


def collect_hits(path: Path, source: str) -> list[tuple[int, int, str]]:
    """与门禁一致：仅含 CJK 的命中；snippet 截断 80 字符以保持历史输出稳定。"""
    raw = collect_literal_hits(path, source, cjk_only=True)
    out: list[tuple[int, int, str]] = []
    for lineno, col, sn in raw:
        short = sn if len(sn) <= 80 else sn[:77] + "..."
        out.append((lineno, col, short))
    return out


def _rel_posix(path: Path, kernel_root: Path) -> str:
    return path.resolve().relative_to(kernel_root.resolve()).as_posix()


def run_scan(cfg: dict[str, Any]) -> list[Hit]:
    kernel_root = _kernel_root(cfg)
    globs = list(cfg.get("scan_globs") or [])
    allow = set(str(x) for x in (cfg.get("legacy_file_allowlist") or []) if str(x).strip())
    segs = list(cfg.get("path_segment_whitelist") or [])

    all_hits: list[Hit] = []
    for path in _iter_scan_files(kernel_root, globs):
        rel = _rel_posix(path, kernel_root)
        if _path_whitelisted(rel, segs):
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as e:
            print(f"[cjk-gate] skip read error {rel}: {e}", file=sys.stderr)
            continue
        for lineno, col, snippet in collect_hits(path, source):
            legacy = rel in allow
            all_hits.append(Hit(path=path, lineno=lineno, col_offset=col, snippet=snippet, legacy=legacy))
    return all_hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bare CJK string literal gate (Step 7)")
    parser.add_argument(
        "--config",
        type=Path,
        default=CONFIG_PATH,
        help="Path to i18n_cjk_gate.json",
    )
    parser.add_argument(
        "--write-allowlist",
        action="store_true",
        help="Rewrite legacy_file_allowlist in config with files that currently have hits",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print every hit including legacy-allowlisted (default: summary only for legacy)",
    )
    args = parser.parse_args(argv)

    cfg = _load_config(args.config)
    mode = (os.environ.get("ADAMI_I18N_CJK_GATE") or "error").strip().lower()
    warn_only = mode == "warn"
    verbose = bool(args.verbose) or os.environ.get("ADAMI_I18N_CJK_GATE_VERBOSE", "").strip() in (
        "1",
        "true",
        "yes",
    )

    hits = run_scan(cfg)
    by_file: dict[str, list[Hit]] = {}
    for h in hits:
        rel = _rel_posix(h.path, _kernel_root(cfg))
        by_file.setdefault(rel, []).append(h)

    if args.write_allowlist:
        files = sorted(by_file.keys())
        cfg["legacy_file_allowlist"] = files
        args.config.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {len(files)} paths to legacy_file_allowlist in {args.config}")
        return 0

    hard = [h for h in hits if not h.legacy]
    soft = [h for h in hits if h.legacy]

    for h in hard:
        rel = _rel_posix(h.path, _kernel_root(cfg))
        print(f"ERROR {rel}:{h.lineno}:{h.col_offset}: {h.snippet!r}", file=sys.stdout)
    if verbose:
        for h in soft:
            rel = _rel_posix(h.path, _kernel_root(cfg))
            print(f"WARN(legacy file) {rel}:{h.lineno}:{h.col_offset}: {h.snippet!r}", file=sys.stderr)
    elif soft:
        legacy_by: dict[str, int] = {}
        for h in soft:
            rel = _rel_posix(h.path, _kernel_root(cfg))
            legacy_by[rel] = legacy_by.get(rel, 0) + 1
        parts = [f"{rel}({n})" for rel, n in sorted(legacy_by.items())]
        print(
            f"[cjk-gate] legacy summary: {len(soft)} hit(s) in allowlisted file(s): " + ", ".join(parts),
            file=sys.stderr,
        )

    if hard:
        print(
            f"[cjk-gate] FAILED: {len(hard)} bare CJK string hit(s) in non-allowlisted files "
            f"({len(by_file)} file(s) with hits). "
            f"Use i18n keys / templates; or add end-of-line `# adami:allow-cjk` with justification.",
            file=sys.stderr,
        )
        if warn_only:
            print("[cjk-gate] ADAMI_I18N_CJK_GATE=warn -> exit 0", file=sys.stderr)
            return 0
        return 1

    if not hits:
        print("[cjk-gate] OK: no bare CJK string literals in scan scope")
    else:
        print(f"[cjk-gate] OK: only legacy-allowlisted hits ({len(soft)} total)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
