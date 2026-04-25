"""步骤 6：非模板长文本翻译（显式调用，与核心路径解耦）。

- 缓存键：``sha256``（规范化 ``source`` / ``target`` / ``scenario`` / 全文）。
- 超时：``asyncio.wait_for`` 包裹 LLM 调用；失败或超长回退**原文**。
- 审计：经 ``ExperienceSink.record_tool_call`` 记录 ``i18n_translate``（便于成本/频率聚合，防翻译风暴）。

仅在业务代码**明确调用** ``translate_text_async`` 时生效；``ADAMI_TRANSLATE_ENABLED=0`` 时立即返回原文。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

from adami_kernel.config import settings
from adami_kernel.i18n.locale_utils import normalize_locale
from adami_kernel.telemetry.experience_sink import (
    experience_episode_id_ctx,
    get_experience_sink,
    summarize_text,
)

logger = logging.getLogger("AdamI-i18n-translate")

_CACHE_VERSION = 1


def _settings_translate_enabled() -> bool:
    """Read ``ADAMI_TRANSLATE_ENABLED``（单测可 ``monkeypatch`` 本函数）。"""
    return bool(getattr(settings, "ADAMI_TRANSLATE_ENABLED", True))


def _settings_translate_max_chars() -> int:
    """Read ``ADAMI_TRANSLATE_MAX_CHARS``（单测可 patch）。"""
    return int(getattr(settings, "ADAMI_TRANSLATE_MAX_CHARS", 50_000))


def _settings_translate_cache_ttl_sec() -> float:
    return float(getattr(settings, "ADAMI_TRANSLATE_CACHE_TTL_SEC", 604800.0))


def translate_cache_root() -> Path:
    raw = getattr(settings, "ADAMI_TRANSLATE_CACHE_DIR", None)
    if raw and str(raw).strip():
        return Path(str(raw).strip()).expanduser()
    return Path(settings.adami_data_dir_path) / "translate_cache"


def make_translate_cache_key(
    text: str,
    target_locale: str,
    *,
    source_locale: Optional[str] = None,
    scenario: str = "generic",
) -> str:
    payload = {
        "v": _CACHE_VERSION,
        "source": normalize_locale(source_locale) if source_locale else "auto",
        "target": normalize_locale(target_locale),
        "scenario": str(scenario or "generic"),
        "text": text,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_file(key: str) -> Path:
    d = translate_cache_root()
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.json"


def _cache_read(key: str) -> Optional[str]:
    p = _cache_file(key)
    if not p.is_file():
        return None
    try:
        ttl = _settings_translate_cache_ttl_sec()
        age = time.time() - p.stat().st_mtime
        if ttl > 0 and age > ttl:
            try:
                p.unlink(missing_ok=True)  # type: ignore[arg-type]
            except OSError:
                pass
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("text"), str):
            return str(data["text"])
    except Exception as e:  # pragma: no cover
        logger.debug("[translate] cache read failed %s: %s", p, e)
    return None


def _cache_write(key: str, translated: str, meta: Dict[str, Any]) -> None:
    p = _cache_file(key)
    try:
        tmp = p.with_suffix(".tmp")
        payload = {"text": translated, "meta": meta, "ts": time.time()}
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    except Exception as e:  # pragma: no cover
        logger.warning("[translate] cache write failed %s: %s", p, e)


def _build_prompt(text: str, *, target_locale: str, source_locale: Optional[str]) -> str:
    tgt = normalize_locale(target_locale)
    src = normalize_locale(source_locale) if source_locale else None
    src_line = f"The source language is approximately: {src}.\n" if src else ""
    return (
        f"Translate the following text into the locale `{tgt}` (BCP-47 style).\n"
        f"{src_line}"
        "Output ONLY the translated text. No quotes, no preamble, no markdown fences.\n\n"
        f"TEXT:\n{text}"
    )


def _audit_tool_call(
    *,
    trace_id: str,
    ok: bool,
    latency_ms: float,
    scenario: str,
    target_locale: str,
    cache_hit: bool,
    char_len: int,
    error_code: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    sink = get_experience_sink()
    core_extra: Dict[str, Any] = {
        "scenario": scenario,
        "target_locale": normalize_locale(target_locale),
        "cache_hit": cache_hit,
        "char_len": char_len,
    }
    if extra:
        core_extra.update(extra)
    sink.record_tool_call(
        trace_id=trace_id,
        tool_name="i18n_translate",
        args_summary=summarize_text(
            f"scenario={scenario} target={target_locale} chars={char_len}", head=300
        ),
        result_summary="ok" if ok else (error_code or "error"),
        ok=ok,
        tool_id="I18N_TRANSLATE",
        tool_backend="native",
        latency_ms=latency_ms,
        extra=core_extra,
    )


async def translate_text_async(
    text: str,
    *,
    target_locale: str,
    call_llm: Callable[[str], Awaitable[str]],
    source_locale: Optional[str] = None,
    scenario: str = "generic",
    timeout_sec: Optional[float] = None,
    trace_id: Optional[str] = None,
) -> str:
    """Translate ``text`` to ``target_locale`` using ``call_llm(prompt) -> str``.

    On any failure, timeout, over-length, or disabled flag: returns **original** ``text``.
    """
    if not _settings_translate_enabled():
        return text
    if not (text or "").strip():
        return text
    tgt = normalize_locale(target_locale)
    src_n = normalize_locale(source_locale) if source_locale else None
    if src_n and src_n == tgt:
        return text

    max_chars = _settings_translate_max_chars()
    if len(text) > max_chars:
        tid = trace_id or f"tr_{uuid.uuid4().hex[:12]}"
        _audit_tool_call(
            trace_id=tid,
            ok=False,
            latency_ms=0.0,
            scenario=scenario,
            target_locale=tgt,
            cache_hit=False,
            char_len=len(text),
            error_code="too_long",
            extra={"max_chars": max_chars},
        )
        return text

    key = make_translate_cache_key(text, tgt, source_locale=source_locale, scenario=scenario)
    cached = _cache_read(key)
    tid = trace_id or experience_episode_id_ctx.get() or f"tr_{uuid.uuid4().hex[:12]}"
    t0 = time.perf_counter()

    if cached is not None:
        _audit_tool_call(
            trace_id=tid,
            ok=True,
            latency_ms=(time.perf_counter() - t0) * 1000,
            scenario=scenario,
            target_locale=tgt,
            cache_hit=True,
            char_len=len(text),
        )
        return cached

    to = float(
        timeout_sec
        if timeout_sec is not None
        else getattr(settings, "ADAMI_TRANSLATE_TIMEOUT_SEC", 30.0)
    )
    prompt = _build_prompt(text, target_locale=tgt, source_locale=source_locale)
    try:
        raw = await asyncio.wait_for(call_llm(prompt), timeout=to)
        out = (raw or "").strip()
        if not out:
            raise ValueError("empty translation")
        latency_ms = (time.perf_counter() - t0) * 1000
        _cache_write(
            key,
            out,
            {"scenario": scenario, "target": tgt, "source": source_locale or "auto"},
        )
        _audit_tool_call(
            trace_id=tid,
            ok=True,
            latency_ms=latency_ms,
            scenario=scenario,
            target_locale=tgt,
            cache_hit=False,
            char_len=len(text),
        )
        return out
    except Exception as e:
        latency_ms = (time.perf_counter() - t0) * 1000
        logger.warning(
            "[translate] failed scenario=%s target=%s: %s", scenario, tgt, e, exc_info=False
        )
        _audit_tool_call(
            trace_id=tid,
            ok=False,
            latency_ms=latency_ms,
            scenario=scenario,
            target_locale=tgt,
            cache_hit=False,
            char_len=len(text),
            error_code=type(e).__name__,
            extra={"detail": summarize_text(str(e), head=200)},
        )
        return text
