# Step 2: kernel-local document → Markdown bridge (MarkItDown). Call sites must not import MarkItDown directly.

from __future__ import annotations

import asyncio
import importlib.util
import logging
from dataclasses import dataclass
from enum import Enum
from importlib.machinery import ModuleSpec
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Final, Union

if TYPE_CHECKING:
    from markitdown import StreamInfo

logger = logging.getLogger("AdamI-DocumentParse")

# Align with DecisionProcessor / tools_manager document excerpts (chars, not tokens).
DEFAULT_MARKDOWN_CHAR_BUDGET: Final[int] = 4000
# Match MultiModalInput unstructured partition timeout.
DEFAULT_CONVERT_TIMEOUT_S: Final[float] = 45.0

ALLOWED_DOCUMENT_EXTENSIONS: Final[frozenset[str]] = frozenset({".pdf", ".docx", ".pptx", ".xlsx"})


class DocumentMarkdownFailureReason(str, Enum):
    """Structured failure for callers (e.g. unstructured fallback)."""

    NOT_INSTALLED = "not_installed"
    DISALLOWED_EXTENSION = "disallowed_extension"
    PATH_MISSING = "path_missing"
    IS_DIRECTORY = "is_directory"
    IO_ERROR = "io_error"
    UNSUPPORTED_FORMAT = "unsupported_format"
    CONVERSION_FAILED = "conversion_failed"
    TIMEOUT = "timeout"
    FILE_TOO_LARGE = "file_too_large"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DocumentMarkdownMeta:
    truncated: bool
    original_char_length: int
    title: str | None = None


@dataclass(frozen=True, slots=True)
class DocumentMarkdownSuccess:
    markdown: str
    meta: DocumentMarkdownMeta


@dataclass(frozen=True, slots=True)
class DocumentMarkdownFailure:
    reason: DocumentMarkdownFailureReason
    detail: str | None = None


DocumentMarkdownResult = Union[DocumentMarkdownSuccess, DocumentMarkdownFailure]


def markitdown_import_spec() -> ModuleSpec | None:
    """Expose spec check for tests (patch target) without importing markitdown."""
    return importlib.util.find_spec("markitdown")


def _resolve_timeout_s(timeout_s: float | None) -> float:
    if timeout_s is not None:
        return float(timeout_s)
    from adami_kernel.config import settings

    return float(settings.ADAMI_DOCUMENT_MARKDOWN_TIMEOUT_SEC)


def _resolve_max_input_bytes(max_input_bytes: int | None) -> int | None:
    """``None`` means use ``Settings``; explicit ``0`` disables the size gate (not recommended)."""
    if max_input_bytes is not None:
        return int(max_input_bytes)
    from adami_kernel.config import settings

    return int(settings.ADAMI_DOCUMENT_MARKDOWN_MAX_INPUT_BYTES)


def normalized_allowed_extension(path_or_name: str | Path) -> str | None:
    """Return normalized suffix (e.g. ``.pdf``) if whitelisted; else ``None``."""
    suf = Path(path_or_name).suffix.lower()
    if suf in ALLOWED_DOCUMENT_EXTENSIONS:
        return suf
    return None


def _apply_char_budget(text: str, max_chars: int) -> tuple[str, bool, int]:
    original = len(text)
    if original <= max_chars:
        return text, False, original
    return text[:max_chars], True, original


class _ConvertThreadError(Exception):
    __slots__ = ("reason", "detail")

    def __init__(self, reason: DocumentMarkdownFailureReason, detail: str | None = None) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason.value}: {detail or ''}")


def _run_markitdown_convert_path(path_str: str) -> tuple[str, str | None]:
    try:
        from markitdown import (
            FileConversionException,
            MarkItDown,
            UnsupportedFormatException,
        )
    except ImportError as e:  # pragma: no cover - guarded by caller
        raise _ConvertThreadError(DocumentMarkdownFailureReason.NOT_INSTALLED, str(e)) from e

    md = MarkItDown(enable_plugins=False)
    try:
        result = md.convert(path_str)
    except UnsupportedFormatException as e:
        raise _ConvertThreadError(DocumentMarkdownFailureReason.UNSUPPORTED_FORMAT, str(e)) from e
    except FileConversionException as e:
        raise _ConvertThreadError(DocumentMarkdownFailureReason.CONVERSION_FAILED, str(e)) from e
    except (OSError, ValueError, TypeError) as e:
        raise _ConvertThreadError(DocumentMarkdownFailureReason.IO_ERROR, str(e)) from e
    except Exception as e:  # pragma: no cover - defensive
        logger.exception("MarkItDown.convert raised unexpected error")
        raise _ConvertThreadError(DocumentMarkdownFailureReason.UNKNOWN, repr(e)) from e

    title = getattr(result, "title", None)
    markdown = str(getattr(result, "markdown", "") or "")
    return markdown, title if isinstance(title, str) else None


def _run_markitdown_convert_stream(
    stream: BinaryIO,
    *,
    stream_info: StreamInfo | None,
    file_extension: str | None,
) -> tuple[str, str | None]:
    try:
        from markitdown import (
            FileConversionException,
            MarkItDown,
            UnsupportedFormatException,
        )
    except ImportError as e:  # pragma: no cover
        raise _ConvertThreadError(DocumentMarkdownFailureReason.NOT_INSTALLED, str(e)) from e

    ext: str | None = None
    if stream_info is not None:
        cand = getattr(stream_info, "extension", None)
        if isinstance(cand, str) and cand:
            ext = cand.lower() if cand.startswith(".") else f".{cand.lower()}"
    if ext is None and file_extension:
        fe = file_extension.lower()
        ext = fe if fe.startswith(".") else f".{fe}"
    if ext is None or ext not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise _ConvertThreadError(
            DocumentMarkdownFailureReason.DISALLOWED_EXTENSION,
            "stream_info.extension or file_extension must be one of "
            f"{sorted(ALLOWED_DOCUMENT_EXTENSIONS)}",
        )

    md = MarkItDown(enable_plugins=False)
    try:
        result = md.convert_stream(stream, stream_info=stream_info, file_extension=file_extension)
    except UnsupportedFormatException as e:
        raise _ConvertThreadError(DocumentMarkdownFailureReason.UNSUPPORTED_FORMAT, str(e)) from e
    except FileConversionException as e:
        raise _ConvertThreadError(DocumentMarkdownFailureReason.CONVERSION_FAILED, str(e)) from e
    except (OSError, ValueError, TypeError) as e:
        raise _ConvertThreadError(DocumentMarkdownFailureReason.IO_ERROR, str(e)) from e
    except Exception as e:  # pragma: no cover
        logger.exception("MarkItDown.convert_stream raised unexpected error")
        raise _ConvertThreadError(DocumentMarkdownFailureReason.UNKNOWN, repr(e)) from e

    title = getattr(result, "title", None)
    markdown = str(getattr(result, "markdown", "") or "")
    return markdown, title if isinstance(title, str) else None


async def convert_document_path_to_markdown(
    path: str | Path,
    *,
    timeout_s: float | None = None,
    max_output_chars: int | None = None,
    max_input_bytes: int | None = None,
) -> DocumentMarkdownResult:
    """
    Convert a local file to Markdown using MarkItDown (``enable_plugins=False``).

    Runs the blocking converter in ``asyncio.to_thread`` with ``asyncio.wait_for``.

    When ``timeout_s`` / ``max_input_bytes`` are omitted, values come from ``Settings``
    (``ADAMI_DOCUMENT_MARKDOWN_TIMEOUT_SEC``, ``ADAMI_DOCUMENT_MARKDOWN_MAX_INPUT_BYTES``).
    """
    p = Path(path)
    ext = normalized_allowed_extension(p.name)
    if ext is None:
        return DocumentMarkdownFailure(
            reason=DocumentMarkdownFailureReason.DISALLOWED_EXTENSION,
            detail=p.suffix or "(no extension)",
        )
    if not p.exists():
        return DocumentMarkdownFailure(
            reason=DocumentMarkdownFailureReason.PATH_MISSING,
            detail=str(p),
        )
    if not p.is_file():
        return DocumentMarkdownFailure(
            reason=DocumentMarkdownFailureReason.IS_DIRECTORY,
            detail=str(p),
        )

    path_str = str(p.resolve())
    max_in = _resolve_max_input_bytes(max_input_bytes)
    if max_in is not None and max_in > 0:
        try:
            sz = p.stat().st_size
        except OSError as e:
            return DocumentMarkdownFailure(
                reason=DocumentMarkdownFailureReason.IO_ERROR,
                detail=str(e),
            )
        if sz > max_in:
            logger.info(
                "[doc.parse] route=markitdown_rejected reason=file_too_large bytes=%s max=%s path=%s",
                sz,
                max_in,
                path_str,
            )
            return DocumentMarkdownFailure(
                reason=DocumentMarkdownFailureReason.FILE_TOO_LARGE,
                detail=f"bytes={sz} max={max_in}",
            )

    if markitdown_import_spec() is None:
        return DocumentMarkdownFailure(
            reason=DocumentMarkdownFailureReason.NOT_INSTALLED,
            detail="install optional extra: poetry install -E markitdown",
        )

    budget = DEFAULT_MARKDOWN_CHAR_BUDGET if max_output_chars is None else max_output_chars
    if budget < 1:
        return DocumentMarkdownFailure(
            reason=DocumentMarkdownFailureReason.UNKNOWN,
            detail="max_output_chars must be >= 1",
        )

    eff_timeout = _resolve_timeout_s(timeout_s)
    try:
        markdown, title = await asyncio.wait_for(
            asyncio.to_thread(_run_markitdown_convert_path, path_str),
            timeout=eff_timeout,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "[doc.parse] route=markitdown_fail reason=timeout timeout_s=%s path=%s",
            eff_timeout,
            path_str,
        )
        return DocumentMarkdownFailure(reason=DocumentMarkdownFailureReason.TIMEOUT)
    except _ConvertThreadError as e:
        logger.warning(
            "[doc.parse] route=markitdown_fail reason=%s path=%s detail=%s",
            e.reason.value,
            path_str,
            (e.detail or "")[:200],
        )
        return DocumentMarkdownFailure(reason=e.reason, detail=e.detail)

    out, truncated, original_len = _apply_char_budget(markdown, budget)
    logger.info(
        "[doc.parse] route=markitdown_ok markdown_chars=%s truncated=%s path=%s",
        len(out),
        int(truncated),
        path_str,
    )
    return DocumentMarkdownSuccess(
        markdown=out,
        meta=DocumentMarkdownMeta(
            truncated=truncated,
            original_char_length=original_len,
            title=title,
        ),
    )


async def convert_document_stream_to_markdown(
    stream: BinaryIO,
    *,
    stream_info: StreamInfo | None = None,
    file_extension: str | None = None,
    timeout_s: float | None = None,
    max_output_chars: int | None = None,
) -> DocumentMarkdownResult:
    """
    Convert a binary stream (MarkItDown-compatible) to Markdown.

    Either ``stream_info.extension`` or ``file_extension`` must identify a whitelisted suffix.

    Omitted ``timeout_s`` uses ``Settings.ADAMI_DOCUMENT_MARKDOWN_TIMEOUT_SEC``.
    """
    if markitdown_import_spec() is None:
        return DocumentMarkdownFailure(
            reason=DocumentMarkdownFailureReason.NOT_INSTALLED,
            detail="install optional extra: poetry install -E markitdown",
        )

    budget = DEFAULT_MARKDOWN_CHAR_BUDGET if max_output_chars is None else max_output_chars
    if budget < 1:
        return DocumentMarkdownFailure(
            reason=DocumentMarkdownFailureReason.UNKNOWN,
            detail="max_output_chars must be >= 1",
        )

    eff_timeout = _resolve_timeout_s(timeout_s)
    try:
        markdown, title = await asyncio.wait_for(
            asyncio.to_thread(
                _run_markitdown_convert_stream,
                stream,
                stream_info=stream_info,
                file_extension=file_extension,
            ),
            timeout=eff_timeout,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "[doc.parse] route=markitdown_fail reason=timeout timeout_s=%s stream=1",
            eff_timeout,
        )
        return DocumentMarkdownFailure(reason=DocumentMarkdownFailureReason.TIMEOUT)
    except _ConvertThreadError as e:
        logger.warning(
            "[doc.parse] route=markitdown_fail reason=%s stream=1 detail=%s",
            e.reason.value,
            (e.detail or "")[:200],
        )
        return DocumentMarkdownFailure(reason=e.reason, detail=e.detail)

    out, truncated, original_len = _apply_char_budget(markdown, budget)
    logger.info(
        "[doc.parse] route=markitdown_ok markdown_chars=%s truncated=%s stream=1",
        len(out),
        int(truncated),
    )
    return DocumentMarkdownSuccess(
        markdown=out,
        meta=DocumentMarkdownMeta(
            truncated=truncated,
            original_char_length=original_len,
            title=title,
        ),
    )
