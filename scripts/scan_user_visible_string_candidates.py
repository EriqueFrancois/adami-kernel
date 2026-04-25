#!/usr/bin/env python3
"""生成「可能对用户可见」的字符串字面量候选列表（AST，排除 docstring / 常见日志 / ``re`` 模式首参）。

默认仅列出 **含 CJK** 的片段（与 Step 7 门禁同一套排除规则），便于 i18n 迁移排期。

用法（仓库根目录）::

  python scripts/scan_user_visible_string_candidates.py
  python scripts/scan_user_visible_string_candidates.py --out reports/candidates.tsv
  python scripts/scan_user_visible_string_candidates.py --include-ascii --min-len 12

CI 会将 ``reports/user_visible_string_candidates.tsv`` 作为 artifact 上传；可在 PR 与 base
分支各下载一份后对 TSV（列 ``path``, ``line``, ``col``, ``snippet``）做 ``diff`` 或按 ``path`` 聚
合，**新增未解释的行**应在 PR 说明中交代（与 Step 7 CJK gate / i18n 迁移计划对齐）。

说明
----
- **不是**语义级「一定展示给用户」：未调用 ``t()`` 的英文长句也会出现在 ``--include-ascii`` 模式下。
- 行尾 ``# adami:allow-cjk`` 与日志 / ``re.compile(r\"...\")`` 首参已排除。
- 跳过 ``**/i18n/locales/**``（catalog 资源）。
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from ast_user_visible_literals import collect_literal_hits  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]


def _iter_py_files(scan_root: Path) -> list[Path]:
    out: list[Path] = []
    for p in sorted(scan_root.rglob("*.py")):
        rel = p.as_posix()
        if "/i18n/locales/" in rel or rel.endswith("/i18n/locales/"):
            continue
        if "__pycache__" in p.parts:
            continue
        out.append(p.resolve())
    return out


def _tsv_cell(s: str) -> str:
    return s.replace("\t", " ").replace("\r", " ").replace("\n", "\\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="User-visible string literal candidate scan")
    ap.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT / "src" / "adami_kernel",
        help="Directory to scan (default: src/adami_kernel)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "reports" / "user_visible_string_candidates.tsv",
        help="Output TSV path",
    )
    ap.add_argument(
        "--markdown",
        type=Path,
        default=None,
        help="Optional second output: Markdown table (default: <out-stem>.md if --out ends with .tsv)",
    )
    ap.add_argument(
        "--include-ascii",
        action="store_true",
        help="Also list ASCII-only literals (no CJK filter); noisy — use with --min-len",
    )
    ap.add_argument(
        "--min-len",
        type=int,
        default=1,
        help="Minimum string length (applies to each literal piece)",
    )
    args = ap.parse_args(argv)

    scan_root = args.root.resolve()
    if not scan_root.is_dir():
        print(f"scan root not a directory: {scan_root}", file=sys.stderr)
        return 2

    cjk_only = not bool(args.include_ascii)
    rows: list[tuple[str, int, int, str]] = []
    err_files = 0
    for path in _iter_py_files(scan_root):
        rel = path.relative_to(scan_root).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as e:
            err_files += 1
            print(f"[skip] {rel}: {e}", file=sys.stderr)
            continue
        for lineno, col, snippet in collect_literal_hits(
            path,
            source,
            cjk_only=cjk_only,
            min_len=int(args.min_len),
        ):
            rows.append((rel, lineno, col, snippet))

    def _rel_repo(p: Path) -> str:
        try:
            return str(p.resolve().relative_to(REPO_ROOT))
        except ValueError:
            return str(p.resolve())

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["path", "line", "col", "snippet"])
        for rel, lineno, col, snippet in rows:
            w.writerow([rel, lineno, col, _tsv_cell(snippet)])

    md_path = args.markdown
    if md_path is None and args.out.suffix.lower() == ".tsv":
        md_path = args.out.with_suffix(".md")
    if md_path is not None:
        md_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            root_disp = str(scan_root.resolve().relative_to(REPO_ROOT))
        except ValueError:
            root_disp = str(scan_root.resolve())
        lines = [
            "# 用户可见字符串候选（自动生成）",
            "",
            f"- 扫描根: `{root_disp}`",
            "- 规则: 排除 docstring、常见 ``logger.*`` 子树、``re.*`` 首参；行尾 ``# adami:allow-cjk`` 排除。",
            f"- 模式: **{'仅含 CJK' if cjk_only else '含 ASCII（见 --include-ascii）'}**，``min_len={args.min_len}``",
            f"- 命中条数: **{len(rows)}**（涉及 **{len({r[0] for r in rows})}** 个文件）",
            "",
            "| path | line | col | snippet |",
            "|------|------|-----|---------|",
        ]
        for rel, lineno, col, snippet in rows[:5000]:
            esc = snippet.replace("|", "\\|").replace("\n", "\\n")[:200]
            lines.append(f"| `{rel}` | {lineno} | {col} | {esc} |")
        if len(rows) > 5000:
            lines.append(f"| … | … | … | *（仅展示前 5000 行，共 {len(rows)} 条）* |")
        md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    by_dir: dict[str, int] = defaultdict(int)
    for rel, _, _, _ in rows:
        top = rel.split("/", 1)[0] if "/" in rel else rel
        by_dir[top] += 1

    print(f"Wrote {len(rows)} row(s) -> {_rel_repo(args.out)}", file=sys.stderr)
    if md_path is not None:
        print(f"Wrote markdown -> {_rel_repo(md_path)}", file=sys.stderr)
    if err_files:
        print(f"[warn] {err_files} file(s) skipped on read error", file=sys.stderr)
    print("Top-level directory counts:", file=sys.stderr)
    for k, v in sorted(by_dir.items(), key=lambda kv: (-kv[1], kv[0]))[:30]:
        print(f"  {k}: {v}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
