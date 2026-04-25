"""PolicyLoader: 轮询 reload 在 manifest 未变化时不应重复打 INFO 热更新日志。"""

import json
import logging
from pathlib import Path

import pytest

from adami_kernel.policy.loader import PolicyLoader


@pytest.fixture()
def policy_dir(tmp_path: Path) -> Path:
    manifest = {
        "version": "0.1.0",
        "prompt_template_paths": {"system": "system.txt"},
        "checksums": {},
    }
    (tmp_path / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    (tmp_path / "system.txt").write_text("hello", encoding="utf-8")
    return tmp_path


def test_reload_safe_silent_when_manifest_unchanged(
    policy_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    loader = PolicyLoader(
        policy_dir=policy_dir,
        manifest_filename="manifest.json",
        reload_interval_sec=9999.0,
    )
    assert loader.get_manifest() is not None

    caplog.clear()
    loader.reload_safe()
    # 内容相同：不应新增任何 INFO（尤其避免每分钟「热更新」刷屏）
    infos = [r for r in caplog.records if r.levelno == logging.INFO]
    assert infos == [], f"expected no INFO logs on noop reload, got: {[r.message for r in infos]}"


def test_reload_safe_logs_when_manifest_version_changes(
    policy_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    loader = PolicyLoader(
        policy_dir=policy_dir,
        manifest_filename="manifest.json",
        reload_interval_sec=9999.0,
    )
    assert loader.get_manifest() is not None
    caplog.clear()

    m2 = {
        "version": "0.2.0",
        "prompt_template_paths": {"system": "system.txt"},
        "checksums": {},
    }
    (policy_dir / "manifest.json").write_text(json.dumps(m2, ensure_ascii=False), encoding="utf-8")
    loader.reload_safe()
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "0.2.0" in joined
