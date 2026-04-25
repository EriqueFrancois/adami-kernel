# --- START OF FILE sensitive_filter.py ---

import logging
import re
from typing import Any, Dict

from adami_kernel.config import settings
from adami_kernel.i18n import t
from adami_kernel.nexus.event import AdamiEvent

logger = logging.getLogger("Guardian-SensitiveFilter")


def _grdsf_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class SensitiveFilter:
    """
    敏感信息过滤中间件（Adami 2.0 工业级安全核心）
    【本次加强修复】：提升 API Key / secret 捕获率，优化日志可见性
    """

    PATTERNS = {
        "api_key": r"(?i)sk-[a-zA-Z0-9]{20,}|AKIA[0-9A-Z]{16}|Bearer\s+[a-zA-Z0-9\-\.]{30,}",
        "password": r'(?i)(?:password|passwd|pwd)\s*[:=]\s*["\']?([^"\'\s]{8,})["\']?',
        "phone": r"(?<!\d)(?:\+?86)?1[3-9]\d{9}(?!\d)",
        "email": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        "credit_card": r"\b(?:\d{4}[ -]?){3}\d{4}\b",
        # 加强 secret 匹配（同时支持独立 sk- 格式）
        "secret": r'(?i)(?:secret|token|auth|key)\s*[:=]\s*["\']?([a-zA-Z0-9\-_=]{24,})["\']?|sk-[a-zA-Z0-9]{20,}',
    }

    def __init__(self):
        self.redacted_count = 0

    def _redact(self, text: str) -> str:
        """统一脱敏：保留上下文，仅擦除核心敏感值"""
        original = text
        for name, pattern in self.PATTERNS.items():
            tag = f"[REDACTED_{name.upper()}]"
            text = re.sub(
                pattern,
                lambda m, _tag=tag: m.group(0).replace(m.group(1), _tag)
                if m.lastindex and m.group(1)
                else _tag,
                text,
            )

        if text != original:
            self.redacted_count += 1
            logger.info(_grdsf_t("grdsf.log.redacted"))
        return text

    def _redact_recursive(self, obj: Any, seen: set = None) -> Any:
        """递归脱敏：防止循环引用死锁"""
        if seen is None:
            seen = set()

        obj_id = id(obj)
        if obj_id in seen:
            return obj
        seen.add(obj_id)

        if isinstance(obj, str):
            return self._redact(obj)

        elif isinstance(obj, dict):
            result = {}
            for k, v in obj.items():
                # 白名单：这些键的值绝对不脱敏
                if k in ("chat_id", "discord_channel_id", "channel_id", "last_chat_id", "user_id"):
                    result[k] = v
                else:
                    result[k] = self._redact_recursive(v, seen)
            return result

        elif isinstance(obj, (list, tuple)):
            return type(obj)(self._redact_recursive(item, seen) for item in obj)

        else:
            return obj

    async def middleware(self, event: AdamiEvent) -> bool:
        """EventBus 中间件：自动脱敏 payload"""
        if not hasattr(event, "payload") or not isinstance(event.payload, dict):
            return True

        # 递归脱敏 Payload 数据
        event.payload = self._redact_recursive(event.payload)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(_grdsf_t("grdsf.debug.payload"))

        return True

    def get_stats(self) -> Dict[str, int]:
        return {"redacted_count": self.redacted_count}


# --- END OF FILE sensitive_filter.py ---
