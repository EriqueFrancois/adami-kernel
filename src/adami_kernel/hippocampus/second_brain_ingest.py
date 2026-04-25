from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional, Sequence

WriteTo = Literal["Inbox", "Resources"]
DedupeStrategy = Literal["overwrite", "append"]


class SecondBrainIngestError(RuntimeError):
    pass


class SecondBrainIngestSafetyError(SecondBrainIngestError):
    pass


_SAFE_SLUG_CHARS = re.compile(r"[^a-z0-9\-]+")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso8601(dt: datetime) -> str:
    # always Zulu
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(text: str, *, max_len: int = 60) -> str:
    raw = (text or "").strip().lower()
    raw = raw.replace("_", "-")
    raw = re.sub(r"\s+", "-", raw)
    raw = _SAFE_SLUG_CHARS.sub("-", raw)
    raw = re.sub(r"-{2,}", "-", raw).strip("-")
    if not raw:
        raw = "note"
    return raw[:max_len].strip("-") or "note"


def _hash8(text: str) -> str:
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return h[:8]


def _ensure_under_root(root: Path, path: Path, *, label: str) -> Path:
    r = root.resolve()
    try:
        p = path.resolve()
    except OSError as e:
        raise SecondBrainIngestSafetyError(f"cannot resolve {label}: {path}") from e
    try:
        p.relative_to(r)
    except ValueError:
        raise SecondBrainIngestSafetyError(f"{label} escapes brain root: {p} (root={r})") from None
    return p


def _normalize_write_to(value: str) -> WriteTo:
    v = (value or "").strip()
    if v in ("Inbox", "Resources"):
        return v  # type: ignore[return-value]
    raise SecondBrainIngestError(f"write_to must be Inbox or Resources, got {value!r}")


def _yaml_escape(s: str) -> str:
    # minimal safe quoting for single-line YAML strings
    val = (s or "").replace("\\", "\\\\").replace('"', '\\"')
    return f'"{val}"'


def _yaml_list(values: Sequence[str]) -> str:
    if not values:
        return "[]"
    inner = ", ".join(_yaml_escape(v) for v in values if str(v).strip())
    return f"[{inner}]"


def _format_frontmatter(
    *,
    para: str,
    title: str,
    summary: Optional[str],
    tags: Sequence[str],
    source: Optional[str],
    dedupe_key: Optional[str],
    created_at: datetime,
    updated_at: datetime,
) -> str:
    lines = ["---"]
    lines.append(f"para: {para}")
    lines.append(f"title: {_yaml_escape(title)}")
    if summary is not None and str(summary).strip():
        lines.append(f"summary: {_yaml_escape(str(summary).strip())}")
    if tags:
        lines.append(f"tags: {_yaml_list(list(tags))}")
    if source is not None and str(source).strip():
        lines.append(f"source: {_yaml_escape(str(source).strip())}")
    if dedupe_key is not None and str(dedupe_key).strip():
        lines.append(f"dedupe_key: {_yaml_escape(str(dedupe_key).strip())}")
    lines.append(f"created_at: {_yaml_escape(_iso8601(created_at))}")
    lines.append(f"updated_at: {_yaml_escape(_iso8601(updated_at))}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def _render_note_md(
    *,
    para: str,
    title: str,
    body_md: str,
    summary: Optional[str],
    tags: Sequence[str],
    source: Optional[str],
    dedupe_key: Optional[str],
    created_at: datetime,
    updated_at: datetime,
) -> str:
    fm = _format_frontmatter(
        para=para,
        title=title,
        summary=summary,
        tags=tags,
        source=source,
        dedupe_key=dedupe_key,
        created_at=created_at,
        updated_at=updated_at,
    )
    body = (body_md or "").rstrip() + "\n"
    return fm + f"# {title.strip()}\n\n" + body


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(path))


def _target_dir(root: Path, write_to: WriteTo) -> Path:
    d = root / write_to
    return _ensure_under_root(root, d, label="target_dir")


def _deterministic_note_filename(*, title: str, dedupe_key: Optional[str], prefix: str) -> str:
    dt = _utc_now()
    date = dt.strftime("%Y-%m-%d")
    s = slugify(title)
    base = f"{prefix}-{date}-{s}"
    if dedupe_key and str(dedupe_key).strip():
        base = f"{base}-{_hash8(str(dedupe_key).strip())}"
    else:
        base = f"{base}-{_hash8(title + date)}"
    return f"{base}.md"


def write_note(
    *,
    brain_root: Path,
    write_to: str,
    title: str,
    body_md: str,
    tags: Optional[Sequence[str]] = None,
    source: Optional[str] = None,
    dedupe_key: Optional[str] = None,
    dedupe_ttl_sec: float = 3600.0,
    dedupe_strategy: DedupeStrategy = "overwrite",
    filename_prefix: str = "note",
) -> Path:
    """
    安全写入一条 SecondBrain 笔记。

    - 仅允许写入 brain_root/{Inbox|Resources}/
    - 命名：prefix + 日期 + slug + hash
    - 去重：若 dedupe_key 提供且目标文件存在，且 mtime 在 TTL 内：
        - overwrite：覆盖（更新 updated_at）
        - append：追加正文（保留历史）
    """
    root = Path(brain_root).expanduser().resolve()
    if not root.exists():
        root.mkdir(parents=True, exist_ok=True)

    to = _normalize_write_to(write_to)
    dir_path = _target_dir(root, to)
    para = to.lower()

    t = (title or "").strip()
    if not t:
        raise SecondBrainIngestError("title is empty")

    tag_list = [str(x).strip() for x in (tags or []) if str(x).strip()]
    prefix = slugify(filename_prefix, max_len=24)
    filename = _deterministic_note_filename(title=t, dedupe_key=dedupe_key, prefix=prefix)
    out = _ensure_under_root(root, dir_path / filename, label="note_path")

    created_at = _utc_now()
    updated_at = created_at

    if dedupe_key and out.exists():
        try:
            age = _utc_now().timestamp() - out.stat().st_mtime
        except OSError:
            age = dedupe_ttl_sec + 1
        if age <= float(dedupe_ttl_sec):
            if dedupe_strategy == "append":
                existing = out.read_text(encoding="utf-8", errors="replace")
                updated_at = _utc_now()
                text = existing.rstrip() + "\n\n---\n\n" + (body_md or "").rstrip() + "\n"
                _atomic_write_text(out, text)
                return out
            # overwrite
            updated_at = _utc_now()
            note_text = _render_note_md(
                para=para,
                title=t,
                body_md=body_md,
                summary=(body_md or "")[:160].strip() if body_md else None,
                tags=tag_list,
                source=source,
                dedupe_key=dedupe_key,
                created_at=created_at,
                updated_at=updated_at,
            )
            _atomic_write_text(out, note_text)
            return out

    note_text = _render_note_md(
        para=para,
        title=t,
        body_md=body_md,
        summary=(body_md or "")[:160].strip() if body_md else None,
        tags=tag_list,
        source=source,
        dedupe_key=dedupe_key,
        created_at=created_at,
        updated_at=updated_at,
    )
    _atomic_write_text(out, note_text)
    return out
