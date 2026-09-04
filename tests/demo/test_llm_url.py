from __future__ import annotations

import pytest

from adami_kernel.demo.cli import main
from adami_kernel.demo.config import load_settings
from adami_kernel.demo.llm_url import assert_safe_llm_base_url


def test_llm_base_url_rejects_private_and_http() -> None:
    with pytest.raises(ValueError):
        assert_safe_llm_base_url("https://127.0.0.1/v1")
    with pytest.raises(ValueError):
        assert_safe_llm_base_url("https://10.1.2.3/v1")
    with pytest.raises(ValueError):
        assert_safe_llm_base_url("https://169.254.169.254/latest")
    with pytest.raises(ValueError):
        assert_safe_llm_base_url("http://api.openai.com/v1")
    with pytest.raises(ValueError):
        assert_safe_llm_base_url("https://localhost/v1")
    assert assert_safe_llm_base_url("https://api.openai.com/v1") == "https://api.openai.com/v1"


def test_llm_base_url_allowlist() -> None:
    with pytest.raises(ValueError):
        assert_safe_llm_base_url("https://evil.example/v1", allowed_hosts=["api.openai.com"])
    assert (
        assert_safe_llm_base_url("https://api.openai.com/v1", allowed_hosts=["api.openai.com"])
        == "https://api.openai.com/v1"
    )


def test_openai_compatible_requires_host_allowlist() -> None:
    s = load_settings(
        LLM_PROVIDER="openai_compatible",
        LLM_API_KEY="not-a-real-key",
        LLM_MODEL="demo",
        LLM_BASE_URL="https://api.openai.com/v1",
        LLM_ALLOWED_HOSTS="",
    )
    assert s.effective_provider() == "fake"
    s2 = load_settings(
        LLM_PROVIDER="openai_compatible",
        LLM_API_KEY="not-a-real-key",
        LLM_MODEL="demo",
        LLM_BASE_URL="https://api.openai.com/v1",
        LLM_ALLOWED_HOSTS="api.openai.com",
    )
    assert s2.effective_provider() == "openai_compatible"


def test_openai_compatible_without_safe_url_stays_fake() -> None:
    s = load_settings(
        LLM_PROVIDER="openai_compatible",
        LLM_API_KEY="not-a-real-key",
        LLM_MODEL="demo",
        LLM_BASE_URL="http://127.0.0.1:9",
    )
    assert s.effective_provider() == "fake"
    assert s.accepted_mode() == "fake"


def test_cli_refuses_secure_cookie_without_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADAMI_DEMO_COOKIE_SECURE", "true")
    monkeypatch.setenv("ADAMI_DEMO_COOKIE_SECRET", "")
    assert main(["--host", "127.0.0.1", "--workers", "1"]) == 2


def test_cli_refuses_requested_live_with_unsafe_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADAMI_DEMO_COOKIE_SECURE", "false")
    monkeypatch.setenv("ADAMI_DEMO_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("ADAMI_DEMO_LLM_API_KEY", "not-a-real-key")
    monkeypatch.setenv("ADAMI_DEMO_LLM_MODEL", "demo")
    monkeypatch.setenv("ADAMI_DEMO_LLM_BASE_URL", "http://127.0.0.1:9")
    assert main(["--host", "127.0.0.1", "--workers", "1"]) == 2
