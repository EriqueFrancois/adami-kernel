from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load_scanlib() -> types.ModuleType:
    scripts = REPO / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import ast_user_visible_literals as m  # noqa: PLC0415

    return m


def test_collect_literal_hits_skips_logger_and_re_pattern() -> None:
    m = _load_scanlib()
    p = REPO / "dummy.py"
    src = (
        'import logging\nlogger = logging.getLogger("x")\n'
        'logger.info("日志中文")\n'
        'import re\nre.compile(r"(密码|pwd)")\n'
        'MSG = "用户可见中文"\n'
    )
    hits = m.collect_literal_hits(p, src, cjk_only=True)
    assert len(hits) == 1
    assert "用户可见" in hits[0][2]


def test_scan_script_writes_tsv(tmp_path: Path) -> None:
    out = tmp_path / "out.tsv"
    r = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "scan_user_visible_string_candidates.py"),
            "--root",
            str(REPO / "tests" / "fixtures" / "cjk_gate_stub"),
            "--out",
            str(out),
            "--markdown",
            str(tmp_path / "out.md"),
        ],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr + r.stdout
    body = out.read_text(encoding="utf-8")
    assert "unallowlisted_bad.py" in body
    assert "你好" in body
