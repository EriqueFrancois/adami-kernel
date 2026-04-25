from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check_no_bare_cjk_strings.py"
STUB_CFG_FAIL = REPO / "tests" / "fixtures" / "cjk_gate_stub" / "config_fail.json"
STUB_CFG_PASS = REPO / "tests" / "fixtures" / "cjk_gate_stub" / "config_pass.json"


def test_cjk_gate_default_config_passes() -> None:
    r = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr + r.stdout


def test_cjk_gate_stub_unallowlisted_fails() -> None:
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--config", str(STUB_CFG_FAIL)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 1
    assert "ERROR" in r.stdout or "ERROR" in r.stderr


def test_cjk_gate_stub_allowlisted_passes() -> None:
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--config", str(STUB_CFG_PASS)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr + r.stdout


@pytest.mark.parametrize(
    "source,expect_hit",
    [
        ('X = "hello"\n', False),
        ('X = "你好"\n', True),
        ('X = "你好"  # adami:allow-cjk\n', False),
        ("import re\nre.compile(r'(密码|pwd)')\n", False),
    ],
)
def test_collect_hits_snippets(source: str, expect_hit: bool, tmp_path: Path) -> None:
    mod_name = "_adami_cjk_gate_probe"
    spec = importlib.util.spec_from_file_location(mod_name, SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(mod_name, None)
    collect_hits = mod.collect_hits

    p = tmp_path / "t.py"
    p.write_text(source, encoding="utf-8")
    hits = collect_hits(p, source)
    assert bool(hits) == expect_hit
