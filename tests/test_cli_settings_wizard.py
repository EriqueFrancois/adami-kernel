"""CLI 配置向导：分类覆盖、解析与 merge 写入。"""

from __future__ import annotations

from pathlib import Path

import pytest

from adami_kernel.config import Settings
from adami_kernel.nexus import cli_settings_wizard as wiz


def test_all_settings_fields_categorized() -> None:
    names = set(Settings.model_fields)
    by = wiz._fields_by_category()
    covered = set().union(*(set(v) for v in by.values()))
    assert names == covered


def test_coerce_bool_int_float_str() -> None:
    fi = Settings.model_fields["DEBUG"]
    assert wiz._coerce_value("DEBUG", fi.annotation, "y") is True
    assert wiz._coerce_value("DEBUG", fi.annotation, "no") is False
    fi2 = Settings.model_fields["ADAMI_HEALTH_PORT"]
    assert wiz._coerce_value("ADAMI_HEALTH_PORT", fi2.annotation, "9090") == 9090
    fi3 = Settings.model_fields["ADAMI_CRITICAL_CPU_PERCENT"]
    assert wiz._coerce_value("x", fi3.annotation, "12.5") == 12.5


def test_coerce_list_str_json() -> None:
    fi = Settings.model_fields["ADAMI_SELF_TEST_CRITICAL_FILES"]
    raw = '["a.py", "b.py"]'
    val = wiz._coerce_value("ADAMI_SELF_TEST_CRITICAL_FILES", fi.annotation, raw)
    assert val == ["a.py", "b.py"]


def test_write_cli_overrides_merge_and_delete(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "cli.env"
    monkeypatch.setattr(wiz, "cli_overrides_env_path", lambda: target)
    wiz.write_cli_overrides({"DEBUG": "true", "ADAMI_HEALTH_PORT": "9001"})
    body = target.read_text()
    assert "DEBUG=true" in body or 'DEBUG="true"' in body
    assert "9001" in body
    wiz.write_cli_overrides({"DEBUG": None})
    body2 = target.read_text()
    assert "DEBUG=true" not in body2 and 'DEBUG="true"' not in body2
    assert "9001" in body2


def test_display_masks_secrets() -> None:
    masked = wiz._display_value("OPENAI_API_KEY", "sk-1234567890abcdef")
    assert "sk-" not in masked
    assert "已设置" in masked or "(set)" in masked.lower()
