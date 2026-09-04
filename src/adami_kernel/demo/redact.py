"""Redact secrets, cookies, session ids, and IPs from logs and error payloads."""

from __future__ import annotations

import re

_COOKIE = re.compile(r"adami_demo_sid=[^;\s]+", re.I)
_SID = re.compile(r"demo:[A-Za-z0-9_-]{8,}")
_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+")
_SK = re.compile(r"(?i)sk-[A-Za-z0-9]{8,}")
_API_KEY_LINE = re.compile(r"(?i)(api[_-]?key|authorization)\s*[:=]\s*\S+")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_CSRF = re.compile(r"(?i)(x-adami-demo-csrf\s*[:=]\s*)\S+")


def redact_text(text: str) -> str:
    s = str(text or "")
    s = _COOKIE.sub("adami_demo_sid=[redacted]", s)
    s = _SID.sub("demo:[redacted]", s)
    s = _BEARER.sub(r"\1[redacted]", s)
    s = _SK.sub("sk-[redacted]", s)
    s = _API_KEY_LINE.sub(r"\1=[redacted]", s)
    s = _CSRF.sub(r"\1[redacted]", s)
    s = _IPV4.sub("[ip-redacted]", s)
    return s


def safe_error_message(message: str) -> str:
    s = redact_text(message)
    if "traceback" in s.lower() or "file \"" in s.lower():
        return "The demonstration service could not complete this turn."
    return s[:400]
