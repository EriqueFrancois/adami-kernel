import asyncio
import logging
import random

from rich.console import Console

from adami_kernel.config import settings

# ====================== 【Bug 12 核心修复】使用公共 JSON 解析器（DRY） ======================
from adami_kernel.cortex.tools.json_parser import extract_json_from_llm_output
from adami_kernel.i18n import t as i18n_t

# =================================================================================

logger = logging.getLogger("AdamI-SubAgent")
console = Console()


def _csub_t(key: str, **kwargs) -> str:
    return i18n_t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class SubAgentManager:
    """子人格管理器：双脑异构并行版，防 API 拥塞"""

    def __init__(self, router, evolution_engine):
        self.router = router
        self.evolution_engine = evolution_engine
        self.semaphore = asyncio.Semaphore(max(1, int(settings.ADAMI_SUB_AGENT_MAX_CONCURRENT)))

    async def _worker(self, task_id: int, task_desc: str, brain_type: str) -> str:
        jitter = random.uniform(0.5, 2.0)
        await asyncio.sleep(jitter)

        console.print(
            _csub_t(
                "csub.console.spawn",
                task_id=task_id,
                brain=brain_type.upper(),
            )
        )

        skills = list(self.evolution_engine.dynamic_skills.keys())
        system_prompt = _csub_t("csub.prompt.system", task_desc=task_desc, skills=str(skills))

        context = []
        for _step in range(3):
            async with self.semaphore:
                response = await self.router.call_llm(
                    prompt="\n".join(context) if context else task_desc,
                    brain_type=brain_type,
                    system_instruction=system_prompt,
                )

            if not response:
                return _csub_t("csub.err.brain_dead", task_id=task_id)

            try:
                # ====================== 【Bug 12 核心修复】统一调用公共 JSON 解析器 ======================
                decision = extract_json_from_llm_output(response)
                # =================================================================================

                if decision is None:
                    context.append("Error: No JSON found in response.")
                    continue

                action = decision.get("action", "")

                if action == "COMPLETE":
                    console.print(_csub_t("csub.console.done", task_id=task_id))
                    return f"Result {task_id}: {decision.get('result', '')}"
                elif action == "CALL_SKILL":
                    s_name = decision.get("skill_name", "").upper()
                    if s_name in self.evolution_engine.dynamic_skills:
                        f = self.evolution_engine.dynamic_skills[s_name]
                        args_dict = decision.get("args", {})
                        out = (
                            await f(**args_dict)
                            if asyncio.iscoroutinefunction(f)
                            else await asyncio.to_thread(f, **args_dict)
                        )
                        context.append(f"Skill {s_name} Result: {out}")
                    else:
                        context.append(f"Error: Skill {s_name} not found.")
            except Exception as e:
                context.append(f"Sub-error: {e}")

        return _csub_t("csub.err.lost", task_id=task_id)

    async def spawn_and_wait(self, tasks: list) -> str:
        if not tasks or not isinstance(tasks, list):
            return "No valid tasks provided."

        console.print(_csub_t("csub.console.orchestrate", n=len(tasks)))

        coroutines = []
        for i, task_desc in enumerate(tasks):
            assigned_brain = "think" if i % 2 == 0 else "action"
            coroutines.append(self._worker(i + 1, task_desc, assigned_brain))

        results = await asyncio.gather(*coroutines)

        console.print(_csub_t("csub.console.fused"))
        return "\n".join(results)
