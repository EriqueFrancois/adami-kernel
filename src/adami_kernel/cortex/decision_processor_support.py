"""Shared helpers for ``DecisionProcessor`` (extracted to reduce coupling / file size)."""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from typing import Any, Dict, Optional

from pydantic import BaseModel

from adami_kernel.config import settings
from adami_kernel.core.kernel_context import KernelContext
from adami_kernel.i18n import t as i18n_t

logger = logging.getLogger("AdamI-DecisionProcessor")


def _dcpu_t(key: str, **kwargs: Any) -> str:
    return i18n_t(key, locale=settings.effective_ui_default_locale(), **kwargs)


_INTAKE_PARA_KEYS = frozenset({"inbox", "projects", "areas", "resources", "archives"})


def _normalize_intake_suggested_para(meta: Dict[str, Any]) -> str:
    raw = meta.get("suggested_para")
    if raw is None or (isinstance(raw, str) and not str(raw).strip()):
        raw = meta.get("target_dir")
    if raw is None:
        return "inbox"
    s = str(raw).strip().lower().replace("\\", "/").rstrip("/")
    s = s.split("/")[-1]
    if s in _INTAKE_PARA_KEYS:
        return s
    aliases = {
        "project": "projects",
        "area": "areas",
        "resource": "resources",
        "archive": "archives",
    }
    return aliases.get(s, "inbox")


def _safe_intake_md_filename(suggested: Optional[Any], fallback: str) -> str:
    if suggested is None:
        return fallback
    base = str(suggested).strip()
    if not base:
        return fallback
    base = os.path.basename(base.replace("\\", "/"))
    if not base.lower().endswith(".md"):
        base = f"{base}.md"
    stem = base[:-3] if base.lower().endswith(".md") else base
    stem = unicodedata.normalize("NFKC", stem)
    out_chars: list[str] = []
    for c in stem:
        if c.isalnum() or c in "-_." or (0x4E00 <= ord(c) <= 0x9FFF):
            out_chars.append(c)
        elif c in " \t":
            out_chars.append("_")
    stem_clean = "".join(out_chars).strip("._-")
    if len(stem_clean) < 1:
        return fallback
    if len(stem_clean) > 100:
        stem_clean = stem_clean[:100]
    name = f"{stem_clean}.md"
    return name if name != ".md" else fallback


def _yaml_single_quoted(value: str) -> str:
    """Escape for single-quoted YAML scalars."""
    return str(value).replace("'", "''")


async def _intake_archive_body_from_payload(
    task: str,
    payload: Dict[str, Any],
    kernel: KernelContext,
) -> tuple[str, str]:
    """
    Step 4: reuse ``MultiModalInput`` document path (MarkItDown-first, unstructured fallback)
    so SecondBrain intake matches multimodal extraction.
    """
    fp = payload.get("file_path")
    if not fp or not isinstance(fp, str) or not os.path.isfile(fp):
        return task, ""
    toolbox = getattr(kernel, "toolbox", None)
    mm = getattr(toolbox, "multi_modal", None) if toolbox is not None else None
    if mm is None:
        return task, ""
    try:
        res = await mm.process_input(
            "document",
            {"file_path": fp, "file_name": str(payload.get("file_name") or "")},
        )
    except Exception as exc:
        logger.warning(_dcpu_t("dcpu.warn.intake_doc_extract", detail=str(exc)))
        return task, ""

    if not isinstance(res, dict) or res.get("type") != "raw_multi_modal":
        return task, ""
    raw = str(res.get("raw_content") or "")
    if not raw.strip():
        return task, ""

    base = (task or "").strip()
    stem = os.path.basename(fp) or "attachment"
    if base and len(base) < 2000 and not base.startswith("/"):
        return f"{base}\n\n---\n\n{raw}", stem
    if base.lower().startswith("/intake"):
        parts = base.split("\n", 1)
        note = parts[1].strip() if len(parts) > 1 else ""
        if note:
            return f"{note}\n\n---\n\n{raw}", stem
    return raw, stem


_STOP_AUDIT_LINE_MAX = 400


def _stop_audit_redact_and_trim(text: str, max_len: int = _STOP_AUDIT_LINE_MAX) -> str:
    """stop_audit 单行摘要：压成一行 + 粗粒度脱敏 + 截断。"""
    if not text or not str(text).strip():
        return ""
    t = str(text).replace("\r", " ").replace("\n", " ")
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"sk-[a-zA-Z0-9]{20,}", "[REDACTED_KEY]", t, flags=re.I)
    t = re.sub(
        r"(?:api[_-]?key|token|secret)\s*[:=]\s*[\"']?[\w\-]{8,}",
        "credential=[REDACTED]",
        t,
        flags=re.I,
    )
    t = re.sub(r"Bearer\s+[\w\-\._~\+/]+=*", "Bearer [REDACTED]", t, flags=re.I)
    t = re.sub(
        r"(password|passwd|pwd|密码)\s*[:=]\s*\S+",
        r"\1=[REDACTED]",
        t,
        flags=re.I,
    )
    if len(t) > max_len:
        t = t[: max_len - 1] + "…"
    return t


class TaskFailedException(Exception):
    """特定任务失败异常，用于熔断后快速释放资源并告知用户"""

    pass


class SkillCreationPlan(BaseModel):
    """严格 Pydantic 模型，用于验证 _create_skill_via_planner 的返回结果"""

    skill_name: str
    # ====================== 【核心修复】赋予默认值，防止验证失败 ======================
    description: str = "User-created or extracted skill"
    # =================================================================================
    code: str = ""
    status: str = "success"
