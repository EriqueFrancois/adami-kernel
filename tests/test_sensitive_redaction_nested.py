"""
步骤 5：敏感信息脱敏 — 结构化嵌套（dict / list / 自引用）回归与扩充用例。

覆盖 ``guardian.sensitive_filter.SensitiveFilter`` 与 ``telemetry.experience_sink.redact_payload``。
"""

from __future__ import annotations

import asyncio
import json

from adami_kernel.guardian.sensitive_filter import SensitiveFilter
from adami_kernel.nexus.event import AdamiEvent, EventPriority
from adami_kernel.telemetry.experience_sink import fingerprint_payload, redact_payload, redact_text

_SK_32 = "sk-abcdefghijklmnopqrstuvwxyz1234567890"


def test_sensitive_filter_nested_dict_and_list_strings() -> None:
    f = SensitiveFilter()
    raw = {
        "meta": {"note": f"key={_SK_32} tail"},
        "rows": [
            {"hint": "user@example.com please"},
            "Bearer " + "a" * 32 + ".b.c",
        ],
    }
    out = f._redact_recursive(raw)
    assert _SK_32 not in str(out)
    assert "user@example.com" not in str(out)
    assert "Bearer " + "a" * 32 not in str(out)
    assert "REDACTED" in str(out) or "[REDACTED" in str(out)


def test_sensitive_filter_tuple_preserved() -> None:
    f = SensitiveFilter()
    raw = {"t": (f"x {_SK_32}", 42)}
    out = f._redact_recursive(raw)
    assert isinstance(out["t"], tuple)
    assert out["t"][1] == 42
    assert _SK_32 not in out["t"][0]


def test_sensitive_filter_cycle_no_recursion_error() -> None:
    f = SensitiveFilter()
    a: dict = {"name": "a", "ref": None}
    b: dict = {"name": "b", "secret": _SK_32, "back": None}
    a["ref"] = b
    b["back"] = a
    out = f._redact_recursive(a)
    assert isinstance(out, dict)
    br = out.get("ref")
    assert isinstance(br, dict)
    assert _SK_32 not in str(br.get("secret", ""))
    assert "[REDACTED" in str(br.get("secret", ""))


def test_sensitive_filter_whitelist_keys_skip_recursion() -> None:
    """白名单键当前实现不递归子值（与实现一致；防止误改行为）。"""
    f = SensitiveFilter()
    raw = {"chat_id": {"nested_token": _SK_32}}
    out = f._redact_recursive(raw)
    assert out["chat_id"] == raw["chat_id"]


def test_sensitive_filter_middleware_nested_payload() -> None:
    f = SensitiveFilter()
    ev = AdamiEvent(
        trace_id="t1",
        source_module="test",
        target_topic="system.events",
        priority=EventPriority.HIGH,
        payload={
            "task": "noop",
            "ctx": {"headers": {"Authorization": "Bearer " + "z" * 40}},
        },
    )

    async def _run() -> None:
        await f.middleware(ev)

    asyncio.run(_run())
    dumped = ev.model_dump()
    assert "zzzz" not in json.dumps(dumped["payload"])


def test_redact_payload_deep_nested_sensitive_keys() -> None:
    raw = {
        "level1": {
            "level2": {
                "api_key": "super-secret-value",
                "Authorization": "Bearer tokentokentoken",
                "innocent": {"deep": {"refresh_token": "rt-99999"}},
            }
        },
        "list": [{"password": "hunter2"}, {"ok": 1}],
    }
    out = redact_payload(raw)
    assert out["level1"]["level2"]["api_key"] == "[REDACTED]"
    assert out["level1"]["level2"]["Authorization"] == "[REDACTED]"
    assert out["level1"]["level2"]["innocent"]["deep"]["refresh_token"] == "[REDACTED]"
    assert out["list"][0]["password"] == "[REDACTED]"
    assert out["list"][1]["ok"] == 1


def test_redact_payload_image_base64_branch() -> None:
    raw = {"payload": {"image_base64": "A" * 200}}
    out = redact_payload(raw)
    assert out["payload"]["image_base64"].startswith("[REDACTED_B64")
    assert "AAA" not in out["payload"]["image_base64"]


def test_redact_payload_strings_in_nested_structure() -> None:
    raw = {
        "messages": [
            {"role": "user", "content": f"here {_SK_32} ends"},
            {"role": "assistant", "content": "password: " + "p" * 12},
        ]
    }
    out = redact_payload(raw)
    c0 = out["messages"][0]["content"]
    assert _SK_32 not in c0
    assert "[REDACTED_KEY]" in c0 or "REDACTED" in c0
    c1 = out["messages"][1]["content"]
    assert "pppp" not in c1 or "REDACTED" in c1


def test_redact_payload_list_truncation_cap() -> None:
    raw = {"items": [{"i": n, "token": str(n)} for n in range(250)]}
    out = redact_payload(raw)
    assert len(out["items"]) == 200


def test_fingerprint_payload_nested_stable_no_raw_secrets() -> None:
    raw = {
        "a": {"api_key": "secret-x"},
        "b": [_SK_32, {"nested": {"token": "y"}}],
    }
    fp1 = fingerprint_payload(raw)
    fp2 = fingerprint_payload(raw)
    assert fp1 == fp2
    assert len(fp1) == 64
    assert "secret-x" not in fp1
    assert _SK_32 not in fp1


def test_redact_text_nested_not_applicable_but_sk_in_flat_string() -> None:
    s = f"prefix {_SK_32} suffix"
    assert _SK_32 not in redact_text(s)
