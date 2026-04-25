from __future__ import annotations

import os
from pathlib import Path


def _write_overrides(path: Path, kv: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# test overrides\n",
    ]
    for k, v in kv.items():
        lines.append(f"{k}={v}\n")
    path.write_text("".join(lines), encoding="utf-8")


def test_validate_startup_prereqs_traversal(tmp_path: Path, monkeypatch) -> None:
    """Traversal test: missing -> configure -> pass."""
    # Force overrides file to a temp location.
    overrides = tmp_path / "cli_overrides.env"
    monkeypatch.setenv("ADAMI_CLI_ENV_FILE", str(overrides))
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    # Ensure no ambient secrets/tokens leak into the test (repo .env or developer shell).
    for k in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "DEEPSEEK_API_KEY",
        "GROQ_API_KEY",
        "GROK_API_KEY",
        "QWEN_API_KEY",
        "GLM_API_KEY",
        "KIMI_API_KEY",
        "MINIMAX_API_KEY",
        "LLM_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "DISCORD_BOT_TOKEN",
    ):
        monkeypatch.delenv(k, raising=False)

    from adami_kernel.config import reload_settings
    from adami_kernel.nexus.first_run_init import validate_startup_prereqs

    # Case 1: completely missing (first run incomplete, no LLM, no profile, no messenger).
    _write_overrides(
        overrides,
        {
            "ADAMI_FIRST_RUN_COMPLETE": "false",
            "OLLAMA_ENABLED": "false",
            "ADAMI_MLX_ENABLED": "false",
            "ADAMI_CLI_ONLY_MODE": "false",
        },
    )
    reload_settings()
    missing = validate_startup_prereqs()
    keys = {m.key for m in missing}
    assert "init" in keys

    # Case 2: configure minimal strict requirements:
    # - mark init complete
    # - runtime profile
    # - local LLM enabled + model
    # - at least one cloud key
    # - messenger enabled and valid routing
    _write_overrides(
        overrides,
        {
            "ADAMI_FIRST_RUN_COMPLETE": "true",
            "ADAMI_RUNTIME_PROFILE": "development",
            "ADAMI_DATA_DIR": ".adami_data",
            "OLLAMA_ENABLED": "true",
            "OLLAMA_MODEL": "qwen3.5:9b",
            "OLLAMA_HOST": "http://127.0.0.1:11434",
            "OPENAI_API_KEY": "dummy-key",
            "TELEGRAM_BOT_TOKEN": "dummy-token",
            "TELEGRAM_CHAT_ID": "123456",
            "ADAMI_CLI_ONLY_MODE": "false",
        },
    )
    reload_settings()
    missing2 = validate_startup_prereqs()
    assert missing2 == []

