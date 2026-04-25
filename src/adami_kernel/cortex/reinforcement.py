import asyncio
import json
import os
import re
from typing import Any

from rich.console import Console

from adami_kernel.config import settings
from adami_kernel.i18n import t

console = Console()


def _crfn_lex(key: str) -> list[Any]:
    return json.loads(t(key, locale="zh-Hans"))


def _crfn_t(key: str, **kwargs: Any) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class RLFeedbackLoop:
    def __init__(self):
        self.skill_weights = {"default": 1.0, "httpx": 2.0}
        self.reward_history = []
        self.model_path = settings.path_rl_weights_json
        self._initialized = False

    async def initialize(self):
        if self._initialized:
            return
        if os.path.exists(self.model_path):
            try:

                def sync_load():
                    with open(self.model_path, "r") as f:
                        data = json.load(f)
                    return data.get("weights", {"default": 1.0, "httpx": 2.0})

                self.skill_weights = await asyncio.to_thread(sync_load)
            except:
                pass
        self._initialized = True

    async def save_weights(self):
        def sync_save():
            with open(self.model_path, "w") as f:
                json.dump({"weights": self.skill_weights}, f)

        await asyncio.to_thread(sync_save)

    async def update_from_feedback(self, feedback_text: str):
        if not self._initialized:
            await self.initialize()

        # 【Advanced RL】解析内容准确性
        price_match = re.search(r"(\d+\.?\d*)", feedback_text)
        price = float(price_match.group(1)) if price_match else 0
        ft_lo = feedback_text.lower()
        trend_positive = any(w in ft_lo for w in _crfn_lex("crfn.lex.trend_positive"))
        trend_negative = any(w in ft_lo for w in _crfn_lex("crfn.lex.trend_negative"))
        nan_error = (
            "nan" in ft_lo
            or "error" in ft_lo
            or any(w in ft_lo for w in _crfn_lex("crfn.lex.nan_markers"))
        )

        accuracy_bonus = 3.0 if (price > 10 and not nan_error) else -2.0 if nan_error else 0
        trend_bonus = 2.0 if trend_positive else -1.5 if trend_negative else 0

        positive = any(w in ft_lo for w in _crfn_lex("crfn.lex.positive"))
        negative = any(w in ft_lo for w in _crfn_lex("crfn.lex.negative"))

        reward = 2.0 + accuracy_bonus + trend_bonus if positive else -1.5 if negative else -0.6
        self.reward_history.append(reward)
        self.skill_weights["default"] = max(0.1, self.skill_weights["default"] + reward * 0.25)
        self.skill_weights["httpx"] = max(0.5, self.skill_weights.get("httpx", 2.0) + reward * 0.4)
        await self.save_weights()
        console.print(
            "[bold cyan]"
            + _crfn_t(
                "crfn.console.accuracy",
                reward=reward,
                accuracy_bonus=accuracy_bonus,
                trend_bonus=trend_bonus,
            )
            + "[/bold cyan]"
        )


rl_loop = RLFeedbackLoop()
