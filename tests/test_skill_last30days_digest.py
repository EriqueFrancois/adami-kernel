from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

import adami_kernel.config as config


def _write_fake_last30days(tmp_path: Path) -> Path:
    p = tmp_path / "fake_last30days.py"
    p.write_text(
        """
import argparse, json, sys
parser = argparse.ArgumentParser()
parser.add_argument("topic")
parser.add_argument("--emit", default="context")
parser.add_argument("--sources", default="auto")
parser.add_argument("--refresh", action="store_true")
args = parser.parse_args()
if args.emit == "json":
    print(json.dumps({"topic": args.topic, "sources": args.sources, "refresh": args.refresh}))
elif args.emit == "path":
    # just emit a non-existent path to exercise parse/read error in higher-level tests (not here)
    print("/tmp/does-not-exist.txt")
else:
    print(f"CTX:{args.topic}")
""".lstrip(),
        encoding="utf-8",
    )
    return p


@pytest.mark.asyncio
async def test_skill_last30days_digest_writes_second_brain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange: enable module + point to fake CLI + isolate SecondBrain root
    fake = _write_fake_last30days(tmp_path)
    brain_root = tmp_path / "brain"
    # NOTE: other tests may call reload_settings() and replace the global settings object.
    # Always patch the live config.settings instance.
    monkeypatch.setattr(config.settings, "ADAMI_LAST30DAYS_ENABLED", True, raising=False)
    monkeypatch.setattr(config.settings, "ADAMI_LAST30DAYS_SCRIPT_PATH", str(fake), raising=False)
    monkeypatch.setattr(config.settings, "ADAMI_LAST30DAYS_PYTHON", sys.executable, raising=False)
    monkeypatch.setattr(config.settings, "ADAMI_SECOND_BRAIN_ROOT", str(brain_root), raising=False)
    monkeypatch.setattr(config.settings, "ADAMI_LAST30DAYS_TRANSLATE_DIGEST", False, raising=False)

    # Import the skill module the same way EvolutionEngine/SkillFileLoader does.
    repo_root = Path(__file__).resolve().parents[1]
    skill_path = (repo_root / ".adami_data" / "skills" / "LAST30DAYS_DIGEST.py").resolve()
    assert skill_path.is_file()
    spec = importlib.util.spec_from_file_location("LAST30DAYS_DIGEST", str(skill_path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    execute = mod.execute

    out = await execute(
        topic="hello", emit="context", write_to="Inbox", refresh=False, sources="auto"
    )
    assert out["ok"] is True
    assert out["note_path"]
    p = Path(out["note_path"])
    assert p.is_file()
    assert "Inbox" in p.parts
    text = p.read_text(encoding="utf-8")
    assert "CTX:hello" in text


@pytest.mark.asyncio
async def test_skill_last30days_digest_translate_calls_llm_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _write_fake_last30days(tmp_path)
    brain_root = tmp_path / "brain"
    monkeypatch.setattr(config.settings, "ADAMI_LAST30DAYS_ENABLED", True, raising=False)
    monkeypatch.setattr(config.settings, "ADAMI_LAST30DAYS_SCRIPT_PATH", str(fake), raising=False)
    monkeypatch.setattr(config.settings, "ADAMI_LAST30DAYS_PYTHON", sys.executable, raising=False)
    monkeypatch.setattr(config.settings, "ADAMI_SECOND_BRAIN_ROOT", str(brain_root), raising=False)
    monkeypatch.setattr(config.settings, "ADAMI_LAST30DAYS_TRANSLATE_DIGEST", True, raising=False)
    monkeypatch.setattr(config.settings, "ADAMI_TRANSLATE_ENABLED", True, raising=False)
    monkeypatch.setattr(config.settings, "ADAMI_UI_LOCALE", "zh-Hans", raising=False)
    monkeypatch.setattr(
        config.settings, "ADAMI_LAST30DAYS_DIGEST_SOURCE_LOCALE", "en", raising=False
    )

    n_calls = {"n": 0}

    async def fake_translate(text: str, **kwargs: object) -> str:
        n_calls["n"] += 1
        return text + "[tr]"

    import adami_kernel.i18n.translate as translate_mod

    monkeypatch.setattr(translate_mod, "translate_text_async", fake_translate)

    repo_root = Path(__file__).resolve().parents[1]
    skill_path = (repo_root / ".adami_data" / "skills" / "LAST30DAYS_DIGEST.py").resolve()
    spec = importlib.util.spec_from_file_location("LAST30DAYS_DIGEST_tr", str(skill_path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    execute = mod.execute

    out = await execute(
        topic="hello", emit="context", write_to="Inbox", refresh=False, sources="auto"
    )
    assert out["ok"] is True
    assert n_calls["n"] == 2
    text = Path(out["note_path"]).read_text(encoding="utf-8")
    assert "[tr]" in text
