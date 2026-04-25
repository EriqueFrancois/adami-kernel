"""策略 manifest / PolicyLoader 单测（不依赖 MLX）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adami_kernel.policy.loader import PolicyLoader, load_manifest
from adami_kernel.policy.manifest import PolicyManifest


def test_policy_manifest_roundtrip() -> None:
    m = PolicyManifest(
        version="1.2.3",
        prompt_template_paths={"system_persona": "t/sys.md"},
        checksums={},
        optional_model_ref="mlx-community/X",
    )
    j = m.model_dump()
    m2 = PolicyManifest.model_validate(j)
    assert m2.version == "1.2.3"
    assert m2.optional_model_ref == "mlx-community/X"


def test_load_manifest_from_dir(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "version": "0.1.0",
                "prompt_template_paths": {"system_persona": "a.md"},
                "checksums": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    m = load_manifest(tmp_path, "manifest.json")
    assert m.version == "0.1.0"


def test_checksum_mismatch_keeps_previous(tmp_path: Path) -> None:
    tmpl = tmp_path / "a.md"
    tmpl.write_text("hello policy", encoding="utf-8")
    bad_manifest = {
        "version": "9.9.9",
        "prompt_template_paths": {"system_persona": "a.md"},
        "checksums": {"a.md": "0" * 64},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(bad_manifest), encoding="utf-8")
    loader = PolicyLoader(
        policy_dir=tmp_path,
        manifest_filename="manifest.json",
        reload_interval_sec=3600.0,
    )
    assert loader.get_manifest() is None

    good_manifest = {
        "version": "1.0.0",
        "prompt_template_paths": {"system_persona": "a.md"},
        "checksums": {},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(good_manifest), encoding="utf-8")
    loader.reload_safe()
    assert loader.get_manifest() is not None
    assert loader.get_manifest().version == "1.0.0"


def test_read_system_templates_concat(tmp_path: Path) -> None:
    (tmp_path / "p1.md").write_text("SYS_A", encoding="utf-8")
    (tmp_path / "p2.md").write_text("SYS_B", encoding="utf-8")
    man = {
        "version": "1",
        "prompt_template_paths": {"system_persona": "p1.md", "system": "p2.md"},
        "checksums": {},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    loader = PolicyLoader(
        policy_dir=tmp_path,
        manifest_filename="manifest.json",
        reload_interval_sec=3600.0,
    )
    text = loader.read_system_templates_from_disk()
    assert "SYS_A" in text and "SYS_B" in text


@pytest.mark.asyncio
async def test_prompt_builder_uses_policy_persona_not_fallback(tmp_path: Path) -> None:
    """验收：PromptBuilder 优先策略包 system 模板，不采用 base persona 原文。"""
    (tmp_path / "persona.md").write_text("POLICY_ONLY_PERSONA", encoding="utf-8")
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "version": "acc-1",
                "prompt_template_paths": {"system_persona": "persona.md"},
                "checksums": {},
            }
        ),
        encoding="utf-8",
    )
    loader = PolicyLoader(
        policy_dir=tmp_path,
        manifest_filename="manifest.json",
        reload_interval_sec=3600.0,
    )
    from adami_kernel.cortex.prompt import PromptBuilder

    pb = PromptBuilder(
        system_persona="SHOULD_NOT_APPEAR_IN_CORE_WHEN_POLICY",
        second_brain=None,
        policy_loader=loader,
    )
    out = await pb.build_action_prompt({"task": "x"}, [], "")
    assert "POLICY_ONLY_PERSONA" in out
    assert "SHOULD_NOT_APPEAR_IN_CORE_WHEN_POLICY" not in out


def test_set_get_policy_loader_singleton(tmp_path: Path) -> None:
    """验收：与 HealthServer 对齐的全局 loader，供 /policy/version 读取。"""
    from adami_kernel.policy.loader import (
        get_policy_loader,
        set_policy_loader,
    )

    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "version": "health-contract",
                "prompt_template_paths": {},
                "checksums": {},
                "optional_model_ref": "ref-xyz",
            }
        ),
        encoding="utf-8",
    )
    loader = PolicyLoader(
        policy_dir=tmp_path,
        manifest_filename="manifest.json",
        reload_interval_sec=3600.0,
    )
    set_policy_loader(loader)
    try:
        pl = get_policy_loader()
        assert pl is loader
        m = pl.get_manifest()
        assert m is not None
        assert m.version == "health-contract"
        assert m.optional_model_ref == "ref-xyz"
    finally:
        set_policy_loader(None)
