"""Demo-only settings. Reads ``ADAMI_DEMO_*`` env vars and never production LLM keys."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DemoSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ADAMI_DEMO_",
        extra="ignore",
        env_file=None,
        case_sensitive=False,
    )

    HOST: str = "127.0.0.1"
    PORT: int = 8091
    COOKIE_SECURE: bool = True
    COOKIE_PATH: str = "/api/demo/"
    ALLOWED_ORIGINS: str = "https://adami.erique.sbs"
    COOKIE_SECRET: str = Field(default="")
    HMAC_SECRET: str = Field(default="")

    LLM_PROVIDER: Literal["fake", "openai_compatible"] = "fake"
    LLM_BASE_URL: str = ""
    LLM_MODEL: str = ""
    LLM_API_KEY: str = ""
    LLM_TIMEOUT_SEC: float = 45.0
    LLM_MAX_OUTPUT_TOKENS: int = 800
    LLM_MAX_PROMPT_CHARS: int = 4000
    LLM_ALLOW_HTTP: bool = False
    LLM_ALLOWED_HOSTS: str = ""

    MAX_TURNS: int = 6
    MAX_INPUT_CHARS: int = 1200
    SESSION_IDLE_TTL_SEC: float = 1800.0
    SESSION_MAX_TTL_SEC: float = 7200.0
    SESSION_CLEANUP_SEC: float = 60.0
    GLOBAL_SLOTS: int = 2
    QUEUE_MAX: int = 8
    WAIT_TIMEOUT_SEC: float = 45.0
    TASK_TIMEOUT_SEC: float = 60.0
    DISCONNECT_GRACE_SEC: float = 2.0
    TERMINAL_RETAIN_SEC: float = 15.0
    RING_MAX_BYTES: int = 32768
    RATE_IP_PER_MINUTE: int = 8
    RATE_IP_PER_DAY: int = 40
    RATE_SESSION_PER_MINUTE: int = 6
    WORKERS: int = 1
    ALLOW_NON_LOOPBACK: bool = False

    @field_validator("LLM_PROVIDER", mode="before")
    @classmethod
    def _norm_provider(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip().lower()
        return v

    def allowed_origin_list(self) -> list[str]:
        return [p.strip().rstrip("/") for p in self.ALLOWED_ORIGINS.split(",") if p.strip()]

    def cookie_secret_bytes(self) -> bytes:
        raw = (self.COOKIE_SECRET or "adami-demo-dev-cookie-secret").encode("utf-8")
        return raw

    def hmac_secret_bytes(self) -> bytes:
        raw = (self.HMAC_SECRET or self.COOKIE_SECRET or "adami-demo-dev-hmac-secret").encode(
            "utf-8"
        )
        return raw

    def effective_provider(self) -> Literal["fake", "openai_compatible"]:
        if self.LLM_PROVIDER != "openai_compatible":
            return "fake"
        if not str(self.LLM_API_KEY or "").strip():
            return "fake"
        if not str(self.LLM_MODEL or "").strip():
            return "fake"
        hosts = self.llm_allowed_host_list()
        if not hosts:
            # Live mode requires an explicit host allowlist so a mis-set URL
            # cannot become an open SSRF proxy via DNS rebinding.
            return "fake"
        from adami_kernel.demo.llm_url import assert_safe_llm_base_url

        try:
            assert_safe_llm_base_url(
                self.LLM_BASE_URL,
                allow_http=self.LLM_ALLOW_HTTP,
                allowed_hosts=hosts,
            )
        except ValueError:
            return "fake"
        return "openai_compatible"

    def llm_allowed_host_list(self) -> list[str]:
        return [p.strip() for p in self.LLM_ALLOWED_HOSTS.split(",") if p.strip()]

    def accepted_mode(self) -> Literal["live", "fake"]:
        return "live" if self.effective_provider() == "openai_compatible" else "fake"


def load_settings(**overrides: object) -> DemoSettings:
    s = DemoSettings()
    if overrides:
        s = s.model_copy(update=overrides)
    return s
