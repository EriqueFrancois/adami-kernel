"""
模块五（last30days-skill）外部 CLI 桥接层。

设计边界：
- 不引入 last30days 的 Python/Node 依赖；仅通过子进程调用外部 `last30days.py`。
- 不使用 shell（避免注入风险）；仅用 `asyncio.create_subprocess_exec`。
- 提供小而稳定的异步 API：`run_last30days(...) -> dict`，供技能层 / 定时触发层调用。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, cast

from adami_kernel.config import settings

logger = logging.getLogger("AdamI-Last30DaysBridge")

EmitMode = Literal["context", "md", "json", "path", "compact"]
SourcesMode = Literal["auto", "reddit", "x", "both"]


class Last30DaysBridgeError(RuntimeError):
    """外部 CLI 调用或解析失败（可用于上层降级/提示）。"""


class Last30DaysBridgeConfigError(Last30DaysBridgeError):
    """配置不合法：脚本不存在、python 不可用、版本不满足等。"""


@dataclass(frozen=True)
class BridgeErrorInfo:
    kind: str
    message: str
    details: Optional[Dict[str, Any]] = None


@dataclass
class _CacheEntry:
    expires_at: float
    value: Dict[str, Any]


_CACHE: Dict[Tuple[str, str, str, bool], _CacheEntry] = {}
_CACHE_LOCK = asyncio.Lock()

# 速率限制：避免定时触发抖动导致短时间重复执行（按 sources + emit 粗粒度限流）
_LAST_RUN_AT: Dict[Tuple[str, str], float] = {}
_RATE_LOCK = asyncio.Lock()


def _truthy(v: object) -> bool:
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "y", "on")


def _now() -> float:
    return time.time()


def _as_emit_mode(value: Optional[str]) -> EmitMode:
    v = (value or "").strip().lower()
    if not v:
        return cast(
            EmitMode, str(getattr(settings, "ADAMI_LAST30DAYS_EMIT_MODE", "context")).lower()
        )
    if v in ("context", "md", "json", "path", "compact"):
        return cast(EmitMode, v)
    raise Last30DaysBridgeConfigError(f"invalid emit mode: {value!r}")


def _as_sources_mode(value: Optional[str]) -> SourcesMode:
    v = (value or "").strip().lower()
    if not v:
        return "auto"
    if v in ("auto", "reddit", "x", "both"):
        return cast(SourcesMode, v)
    raise Last30DaysBridgeConfigError(f"invalid sources mode: {value!r}")


async def _python_version_ok(exe: str, *, min_version: Tuple[int, int] = (3, 12)) -> bool:
    """
    通过子进程检查解释器版本（不依赖当前进程版本）。
    返回 True/False，不抛异常（由调用者构建结构化错误）。
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            exe,
            "-c",
            "import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        if proc.returncode == 0:
            return True
        # 兼容未来：若要求不是 (3,12) 可扩展（当前仅用 3.12+）
        if min_version != (3, 12):
            proc2 = await asyncio.create_subprocess_exec(
                exe,
                "-c",
                f"import sys; raise SystemExit(0 if sys.version_info >= {min_version!r} else 1)",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc2.wait()
            return proc2.returncode == 0
        return False
    except Exception:
        return False


async def _resolve_python_executable(
    explicit: Optional[str],
) -> Tuple[Optional[str], Optional[BridgeErrorInfo]]:
    """
    按优先级选择 Python：显式指定 > settings 默认 > 探测 python3.13/python3.12/python3。
    并校验 3.12+。
    """
    candidates: List[str] = []
    if explicit and str(explicit).strip():
        candidates.append(str(explicit).strip())
    cfg = (getattr(settings, "ADAMI_LAST30DAYS_PYTHON", None) or "").strip()
    if cfg and cfg not in candidates:
        candidates.append(cfg)
    for p in ("python3.13", "python3.12", "python3"):
        if p not in candidates:
            candidates.append(p)

    for exe in candidates:
        ok = await _python_version_ok(exe, min_version=(3, 12))
        if ok:
            return exe, None

    return None, BridgeErrorInfo(
        kind="python_not_found_or_too_old",
        message="last30days requires Python 3.12+; no suitable interpreter found.",
        details={"candidates": candidates},
    )


def _resolve_script_path(
    explicit: Optional[str],
) -> Tuple[Optional[str], Optional[BridgeErrorInfo]]:
    raw = (explicit or getattr(settings, "ADAMI_LAST30DAYS_SCRIPT_PATH", None) or "").strip()
    if not raw:
        return None, BridgeErrorInfo(
            kind="script_path_missing",
            message="ADAMI_LAST30DAYS_SCRIPT_PATH is empty; cannot run last30days external CLI.",
        )
    p = Path(raw).expanduser()
    if not p.is_file():
        return None, BridgeErrorInfo(
            kind="script_not_found",
            message=f"last30days.py not found: {str(p)!r}",
            details={"path": str(p)},
        )
    return str(p), None


def _cache_key(
    topic: str, emit: EmitMode, sources: SourcesMode, refresh: bool
) -> Tuple[str, str, str, bool]:
    return (topic.strip(), str(emit), str(sources), bool(refresh))


async def _cache_get(key: Tuple[str, str, str, bool]) -> Optional[Dict[str, Any]]:
    async with _CACHE_LOCK:
        ent = _CACHE.get(key)
        if not ent:
            return None
        if _now() >= ent.expires_at:
            _CACHE.pop(key, None)
            return None
        return dict(ent.value)


async def _cache_put(
    key: Tuple[str, str, str, bool], value: Dict[str, Any], *, ttl_sec: float
) -> None:
    async with _CACHE_LOCK:
        _CACHE[key] = _CacheEntry(expires_at=_now() + max(0.0, float(ttl_sec)), value=dict(value))


async def _rate_limit_check(
    *,
    sources: SourcesMode,
    emit: EmitMode,
    min_interval_sec: float,
) -> Optional[BridgeErrorInfo]:
    """
    Scheduled trigger rate limit.

    For a given pair of (sources, emit), allow at most one execution within
    `min_interval_sec`. Returns error info when rate-limited, otherwise None.
    """
    key = (str(sources), str(emit))
    now = _now()
    async with _RATE_LOCK:
        last = _LAST_RUN_AT.get(key)
        if last is not None and now - last < float(min_interval_sec):
            return BridgeErrorInfo(
                kind="rate_limited",
                message=f"rate limited: last run {now - last:.1f}s ago (<{min_interval_sec}s)",
                details={
                    "sources": sources,
                    "emit": emit,
                    "min_interval_sec": float(min_interval_sec),
                },
            )
        _LAST_RUN_AT[key] = now
        return None


def _build_args(
    topic: str,
    *,
    emit: EmitMode,
    sources: SourcesMode,
    refresh: bool,
) -> List[str]:
    args = [topic]
    if refresh:
        args.append("--refresh")
    # last30days supports compact|json|md|context|path; we pass through.
    args.append(f"--emit={emit}")
    args.append(f"--sources={sources}")
    return args


def _safe_decode(b: bytes) -> str:
    return b.decode("utf-8", errors="replace")


def _parse_emit(
    *,
    emit: EmitMode,
    stdout_text: str,
) -> Tuple[Optional[Any], List[str], Optional[BridgeErrorInfo]]:
    """
    解析 stdout：
    - json: 解析 JSON
    - path: stdout 视为文件路径（取最后一行），返回 paths
    - md/context/compact: 直接文本
    """
    if emit == "json":
        try:
            return json.loads(stdout_text), [], None
        except json.JSONDecodeError as e:
            return (
                None,
                [],
                BridgeErrorInfo(
                    kind="parse_error",
                    message=f"failed to parse JSON stdout: {e}",
                ),
            )
    if emit == "path":
        line = (stdout_text or "").strip().splitlines()[-1] if (stdout_text or "").strip() else ""
        if not line:
            return (
                None,
                [],
                BridgeErrorInfo(kind="parse_error", message="emit=path but stdout empty"),
            )
        return line, [line], None
    # context / md / compact
    return stdout_text, [], None


async def _read_text_file(
    path: str, *, max_bytes: int = 2_000_000
) -> Tuple[Optional[str], Optional[BridgeErrorInfo]]:
    try:
        p = Path(path).expanduser()
        if not p.is_file():
            return None, BridgeErrorInfo(
                kind="path_not_found", message=f"output file not found: {path!r}"
            )
        data = await asyncio.to_thread(p.read_bytes)
        if len(data) > max_bytes:
            data = data[:max_bytes]
        return data.decode("utf-8", errors="replace"), None
    except Exception as e:
        return None, BridgeErrorInfo(kind="read_error", message=f"failed to read output file: {e}")


async def _fallback_min_briefing_md(topic: str) -> str:
    """
    可选降级：用 ddgs 做一个“最小简报”。
    注意：这是软降级（不保证网络可用）；失败时返回可读文本。
    """
    try:
        from ddgs import DDGS  # type: ignore
    except Exception:
        return f"last30days unavailable. (fallback web search backend not available)\n\ntopic: {topic}\n"

    query = f"{topic} last 30 days summary"
    try:
        with DDGS() as ddgs:
            rows = list(ddgs.text(query, max_results=5))
        lines = [f"## Fallback brief: {topic}", "", f"query: {query}", ""]
        for r in rows:
            title = str(r.get("title", "") or "").strip()
            href = str(r.get("href", "") or "").strip()
            body = str(r.get("body", "") or "").strip()
            if not (title or href or body):
                continue
            lines.append(f"- **{title}**")
            if href:
                lines.append(f"  - {href}")
            if body:
                lines.append(f"  - {body}")
        return "\n".join(lines).strip() + "\n"
    except Exception as e:
        return f"last30days unavailable. (fallback web search failed: {e})\n\ntopic: {topic}\n"


async def run_last30days(
    topic: str,
    *,
    emit: Optional[str] = None,
    sources: Optional[str] = None,
    refresh: Optional[bool] = None,
    timeout: Optional[float] = None,
    script_path: Optional[str] = None,
    python_executable: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    cache_ttl_sec: float = 300.0,
    enable_cache: bool = True,
    min_interval_sec: float = 30.0,
    enforce_rate_limit: bool = False,
    read_path_output: bool = True,
    fallback_to_web_search: bool = False,
) -> Dict[str, Any]:
    """
    调用外部 last30days.py 并解析输出。

    返回结构（稳定形状）：
    - ok: bool
    - stdout/stderr/exit_code
    - emit/sources/refresh/timeout_sec
    - parsed: Any（json->dict/list；context/md/compact->str；path->str 或 file content）
    - output_paths: list[str]
    - cache_hit: bool
    - error: {kind,message,details}?（失败时）
    """
    t = (topic or "").strip()
    if not t:
        return {
            "ok": False,
            "stdout": "",
            "stderr": "",
            "exit_code": -1,
            "emit": None,
            "sources": None,
            "refresh": False,
            "timeout_sec": None,
            "parsed": None,
            "output_paths": [],
            "cache_hit": False,
            "error": {"kind": "invalid_input", "message": "topic is empty", "details": None},
        }

    em = _as_emit_mode(emit)
    sm = _as_sources_mode(sources)
    rf = (
        bool(refresh)
        if refresh is not None
        else bool(getattr(settings, "ADAMI_LAST30DAYS_REFRESH_DEFAULT", False))
    )
    to = (
        float(timeout)
        if timeout is not None
        else float(getattr(settings, "ADAMI_LAST30DAYS_TIMEOUT_SEC", 120.0))
    )

    key = _cache_key(t, em, sm, rf)
    if enable_cache:
        cached = await _cache_get(key)
        if cached is not None:
            cached["cache_hit"] = True
            return cached

    if enforce_rate_limit:
        rl = await _rate_limit_check(sources=sm, emit=em, min_interval_sec=min_interval_sec)
        if rl is not None:
            return {
                "ok": False,
                "stdout": "",
                "stderr": "",
                "exit_code": -1,
                "emit": em,
                "sources": sm,
                "refresh": rf,
                "timeout_sec": to,
                "parsed": None,
                "output_paths": [],
                "cache_hit": False,
                "error": {"kind": rl.kind, "message": rl.message, "details": rl.details},
            }

    sp, sp_err = _resolve_script_path(script_path)
    if sp_err is not None:
        out = {
            "ok": False,
            "stdout": "",
            "stderr": "",
            "exit_code": -1,
            "emit": em,
            "sources": sm,
            "refresh": rf,
            "timeout_sec": to,
            "parsed": None,
            "output_paths": [],
            "cache_hit": False,
            "error": {"kind": sp_err.kind, "message": sp_err.message, "details": sp_err.details},
        }
        if fallback_to_web_search:
            out["parsed"] = await _fallback_min_briefing_md(t)
            out["emit"] = "md"
        return out

    py, py_err = await _resolve_python_executable(python_executable)
    if py_err is not None or not py:
        out = {
            "ok": False,
            "stdout": "",
            "stderr": "",
            "exit_code": -1,
            "emit": em,
            "sources": sm,
            "refresh": rf,
            "timeout_sec": to,
            "parsed": None,
            "output_paths": [],
            "cache_hit": False,
            "error": {
                "kind": py_err.kind if py_err else "python_error",
                "message": py_err.message if py_err else "python error",
                "details": py_err.details if py_err else None,
            },
        }
        if fallback_to_web_search:
            out["parsed"] = await _fallback_min_briefing_md(t)
            out["emit"] = "md"
        return out

    argv = [py, sp] + _build_args(t, emit=em, sources=sm, refresh=rf)
    proc_env = os.environ.copy()
    if env:
        proc_env.update({str(k): str(v) for k, v in env.items()})

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=proc_env,
        )
    except Exception as e:
        out = {
            "ok": False,
            "stdout": "",
            "stderr": str(e),
            "exit_code": -1,
            "emit": em,
            "sources": sm,
            "refresh": rf,
            "timeout_sec": to,
            "parsed": None,
            "output_paths": [],
            "cache_hit": False,
            "error": {
                "kind": "spawn_failed",
                "message": f"failed to spawn last30days subprocess: {e}",
                "details": {"argv": argv},
            },
        }
        if fallback_to_web_search:
            out["parsed"] = await _fallback_min_briefing_md(t)
            out["emit"] = "md"
        return out

    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=to)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        out = {
            "ok": False,
            "stdout": "",
            "stderr": f"Execution timed out after {to}s",
            "exit_code": -1,
            "emit": em,
            "sources": sm,
            "refresh": rf,
            "timeout_sec": to,
            "parsed": None,
            "output_paths": [],
            "cache_hit": False,
            "error": {
                "kind": "timeout",
                "message": "last30days execution timed out",
                "details": {"timeout_sec": to},
            },
        }
        if fallback_to_web_search:
            out["parsed"] = await _fallback_min_briefing_md(t)
            out["emit"] = "md"
        return out

    stdout_t = _safe_decode(stdout_b or b"")
    stderr_t = _safe_decode(stderr_b or b"")
    rc = int(proc.returncode if proc.returncode is not None else -1)

    parsed, output_paths, parse_err = _parse_emit(emit=em, stdout_text=stdout_t)
    if rc != 0 and fallback_to_web_search:
        parsed = await _fallback_min_briefing_md(t)
        output_paths = []
        parse_err = None
        em = "md"

    if rc == 0 and em == "path" and read_path_output and isinstance(parsed, str) and parsed.strip():
        file_text, read_err = await _read_text_file(parsed.strip())
        if read_err is None:
            parsed = file_text
        else:
            parse_err = parse_err or read_err

    ok = (rc == 0) and (parse_err is None)
    out: Dict[str, Any] = {
        "ok": ok,
        "stdout": stdout_t,
        "stderr": stderr_t,
        "exit_code": rc,
        "emit": em,
        "sources": sm,
        "refresh": rf,
        "timeout_sec": to,
        "parsed": parsed if ok or fallback_to_web_search else None,
        "output_paths": list(output_paths),
        "cache_hit": False,
        "error": None,
    }

    if not ok:
        if parse_err is not None:
            out["error"] = {
                "kind": parse_err.kind,
                "message": parse_err.message,
                "details": parse_err.details,
            }
        elif rc != 0:
            out["error"] = {
                "kind": "execution_failed",
                "message": f"last30days exited with code {rc}",
                "details": {"stderr": stderr_t[-2000:], "argv": argv},
            }
        else:
            out["error"] = {
                "kind": "unknown_error",
                "message": "unknown error",
                "details": {"argv": argv},
            }

    if enable_cache and ok:
        await _cache_put(key, out, ttl_sec=float(cache_ttl_sec))

    return out
