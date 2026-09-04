"""OpenAI-compatible chat completions adapter. No local-model fallback."""

from __future__ import annotations

import httpx

from adami_kernel.demo.llm_url import assert_safe_llm_base_url
from adami_kernel.demo.redact import redact_text


class OpenAICompatibleLLM:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        allow_http: bool = False,
        allowed_hosts: list[str] | None = None,
    ) -> None:
        self._base = assert_safe_llm_base_url(
            base_url, allow_http=allow_http, allowed_hosts=allowed_hosts
        )
        self._model = model
        self._api_key = api_key

    async def complete(self, *, prompt: str, max_tokens: int, timeout_sec: float) -> str:
        url = f"{self._base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self._model,
            "stream": False,
            "max_tokens": int(max_tokens),
            "messages": [{"role": "user", "content": prompt}],
        }
        try:
            async with httpx.AsyncClient(
                timeout=timeout_sec,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                r = await client.post(url, headers=headers, json=body)
        except httpx.TimeoutException:
            raise RuntimeError("model timeout") from None
        except Exception as exc:
            raise RuntimeError(redact_text(str(exc))) from None
        if r.status_code == 429:
            raise RuntimeError("model rate limited")
        if r.status_code >= 500:
            raise RuntimeError("model unavailable")
        if r.status_code >= 400:
            raise RuntimeError("model request failed")
        try:
            data = r.json()
            return str(data["choices"][0]["message"]["content"] or "")
        except Exception:
            raise RuntimeError("unexpected model response") from None
