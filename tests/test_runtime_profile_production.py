"""``ADAMI_RUNTIME_PROFILE`` + production-safe defaults (Docker sandbox policy)."""

from __future__ import annotations

import pathlib

import pytest

from adami_kernel.config import Settings


def _clear_profile_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in (
        "ADAMI_RUNTIME_PROFILE",
        "ADAMI_SKIP_DOCKER_SANDBOX",
        "DEBUG",
        "ADAMI_DOCKER_SANDBOX_READ_ONLY_ROOTFS",
        "ADAMI_DOCKER_SANDBOX_DROP_ALL_CAPABILITIES",
        "ADAMI_DOCKER_SANDBOX_NO_NEW_PRIVILEGES",
    ):
        monkeypatch.delenv(k, raising=False)


def test_production_profile_sets_docker_and_hardening_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_profile_env(monkeypatch)
    monkeypatch.setenv("ADAMI_RUNTIME_PROFILE", "production")
    s = Settings(_env_file=())
    assert s.ADAMI_RUNTIME_PROFILE == "production"
    assert s.ADAMI_SKIP_DOCKER_SANDBOX is False
    assert s.DEBUG is False
    assert s.ADAMI_DOCKER_SANDBOX_READ_ONLY_ROOTFS is True
    assert s.ADAMI_DOCKER_SANDBOX_DROP_ALL_CAPABILITIES is True
    assert s.ADAMI_DOCKER_SANDBOX_NO_NEW_PRIVILEGES is True


def test_production_respects_explicit_skip_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADAMI_RUNTIME_PROFILE", "production")
    monkeypatch.setenv("ADAMI_SKIP_DOCKER_SANDBOX", "1")
    monkeypatch.delenv("DEBUG", raising=False)
    s = Settings(_env_file=())
    assert s.ADAMI_SKIP_DOCKER_SANDBOX is True


def test_development_keeps_skip_docker_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADAMI_RUNTIME_PROFILE", "development")
    monkeypatch.delenv("ADAMI_SKIP_DOCKER_SANDBOX", raising=False)
    s = Settings(_env_file=())
    assert s.ADAMI_SKIP_DOCKER_SANDBOX is True


def test_auto_profile_production_in_container(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_profile_env(monkeypatch)
    _orig = pathlib.Path.is_file

    def _patched(self: pathlib.Path) -> bool:
        if str(self) == "/.dockerenv":
            return True
        return _orig(self)

    monkeypatch.setattr(pathlib.Path, "is_file", _patched)
    s = Settings(_env_file=())
    assert s.ADAMI_RUNTIME_PROFILE == "production"
    assert s.ADAMI_SKIP_DOCKER_SANDBOX is False


def test_auto_profile_development_on_host(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_profile_env(monkeypatch)
    s = Settings(_env_file=())
    assert s.ADAMI_RUNTIME_PROFILE == "development"
    assert s.ADAMI_SKIP_DOCKER_SANDBOX is True
