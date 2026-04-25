"""OpenAI 兼容 chat/completions 单次调用（技能等无 Router 上下文场景）。

使用与 ``HybridLLMRouter`` 相同的 ``get_router_action_providers()`` 配置与密钥字段，
避免在 ``LAST30DAYS_DIGEST`` 等模块中 ``import`` ``cortex.router``（会触发 MLX 等重路径）。
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from adami_kernel.config import get_router_action_providers, settings

logger = logging.getLogger("AdamI-MinimalOpenAIChat")


async def one_shot_completion(
    prompt: str,
    *,
    temperature: float = 0.2,
    max_tokens: int = 8192,
) -> str:
    providers = [p for p in get_router_action_providers() if p.get("api_key")]
    if not providers:
        raise RuntimeError("MinimalOpenAIChat: no action provider with api_key configured")

    want = str(getattr(settings, "ADAMI_FAST_MODEL", "") or "").strip().lower()
    pick: dict[str, Any] | None = None
    for p in providers:
        if str(p.get("model") or "").strip().lower() == want:
            pick = p
            break
    pick = pick or providers[0]

    headers = {
        "Authorization": f"Bearer {pick['api_key']}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": pick["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    timeout = httpx.Timeout(120.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(str(pick["base_url"]), headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
        text = str(data["choices"][0]["message"]["content"] or "")
        return re.sub(
            r"<think>.*?</think>",
            "",
            text,
            flags=re.DOTALL,
        ).strip()
