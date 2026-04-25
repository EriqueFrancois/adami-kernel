# -*- coding: utf-8 -*-
"""Step 7（裸中文字面量门禁）— 验收测试（自动化）

验收方案（概要）
================

1. **配置契约**：仓库内存在 ``scripts/i18n_cjk_gate.json``，``version == 1``，
   ``scan_globs`` 非空；须覆盖 nexus（显式 glob 或整包 ``**/*.py``）且须覆盖 ``cortex/decision_processor.py``（整包 glob 已含）。

2. **CI 门禁脚本可执行**：默认配置下 ``python scripts/check_no_bare_cjk_strings.py`` exit 0；
   仅 legacy 命中时 stderr 含 ``legacy summary``（不引入新裸中文于非豁免文件）。

3. **失败路径**：未列入 ``legacy_file_allowlist`` 的扫描目标含裸 CJK 字面量时 exit 1，
   且输出含 ``ERROR``（夹具 ``tests/fixtures/cjk_gate_stub/``）。

4. **豁免路径**：同一违规文件列入 ``legacy_file_allowlist`` 后 exit 0（渐进收紧清单）。

5. **AST 规则（抽样）**：docstring 内中文不计命中；``logger.info("…中文…")`` 子树不计命中。

6. **渐进模式**：``ADAMI_I18N_CJK_GATE=warn`` 时，对「本应失败」的夹具配置仍 exit 0（仅警告）。

与 ``tests/test_i18n_cjk_gate.py`` 单测互补；本文件侧重验收级契约与运维开关。

执行::

  poetry run pytest tests/test_acceptance_i18n_step7_cjk_gate.py \\
    tests/test_i18n_cjk_gate.py -v

门禁脚本::

  poetry run python scripts/check_no_bare_cjk_strings.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check_no_bare_cjk_strings.py"
CONFIG = REPO / "scripts" / "i18n_cjk_gate.json"
STUB_CFG_FAIL = REPO / "tests" / "fixtures" / "cjk_gate_stub" / "config_fail.json"


def test_acceptance_step7_config_contract() -> None:
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert int(data["version"]) == 1
    globs = list(data.get("scan_globs") or [])
    assert globs, "scan_globs must be non-empty"
    full_kernel = any(g.strip().lstrip("/") in ("**/*.py", "./**/*.py") for g in globs)
    assert full_kernel or any("nexus/" in g for g in globs), "must scan nexus (explicit or **/*.py)"
    assert (
        full_kernel or "cortex/decision_processor.py" in globs
    ), "must scan decision_processor (explicit or **/*.py)"
    assert isinstance(data.get("legacy_file_allowlist"), list)


def test_acceptance_step7_default_script_ok_and_legacy_summary() -> None:
    r = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr + r.stdout
    assert "legacy summary" in r.stderr or "OK:" in r.stdout


@pytest.mark.parametrize(
    "source,expect_hit",
    [
        ('"""模块说明：中文"""\nX = "hello"\n', False),
        (
            '"""模块说明"""\nimport logging\nlogging.getLogger(__name__)\nlogger = logging.getLogger("x")\nlogger.info("日志中文")\n',
            False,
        ),
        ('"""模块说明"""\nY = "界面中文"\n', True),
    ],
)
def test_acceptance_step7_ast_docstring_and_logger_skips(
    source: str,
    expect_hit: bool,
    tmp_path: Path,
) -> None:
    mod_name = "_adami_cjk_gate_acceptance"
    spec = importlib.util.spec_from_file_location(mod_name, SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(mod_name, None)

    p = tmp_path / "sample.py"
    p.write_text(source, encoding="utf-8")
    hits = mod.collect_hits(p, source)
    assert bool(hits) == expect_hit


def test_acceptance_step7_warn_mode_stub_still_zero_exit() -> None:
    env = {**os.environ, "ADAMI_I18N_CJK_GATE": "warn"}
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--config", str(STUB_CFG_FAIL)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert r.returncode == 0, r.stderr + r.stdout
