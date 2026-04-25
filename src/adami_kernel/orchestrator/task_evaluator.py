import json
import logging
import re
from typing import Any, Dict, Optional

from adami_kernel.config import settings
from adami_kernel.cortex.router import LLMRouter
from adami_kernel.cortex.tools.json_parser import extract_json_from_llm_output
from adami_kernel.i18n import t
from adami_kernel.i18n.ui_static import catalog_pipe_tokens, task_matches_pipe_catalog

logger = logging.getLogger("AdamI-TaskEvaluator")


def _te_t(key: str, **kwargs: Any) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class TaskEvaluator:
    """任务完成度评估器，用于判断任务执行结果是否满足原始需求"""

    def __init__(self, router: LLMRouter):
        self.router = router

    def _extract_city(self, text: str) -> Optional[str]:
        if not text:
            return None
        common_cities = list(catalog_pipe_tokens("shared.pipe.common_cities_cn"))
        for city in common_cities:
            if city in text:
                return city
        match = re.search(r"([\u4e00-\u9fff]{2,4})", text)
        return match.group(1) if match else None

    async def evaluate(
        self,
        original_task: str,
        current_result: str,
        previous_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if isinstance(current_result, dict):
            result_data = current_result
        else:
            try:
                result_data = json.loads(current_result)
            except (json.JSONDecodeError, TypeError):
                result_data = None

        logger.debug(_te_t("te.log.debug_result", data=str(result_data)[:3000]))

        if result_data and isinstance(result_data, dict):
            if "execution_result" in result_data:
                execution_result = result_data.get("execution_result")
            else:
                executor_data = result_data.get("executor", {})
                execution_result = executor_data.get("execution_result")

            if execution_result and isinstance(execution_result, dict):
                if execution_result.get("status") == "success":
                    data = execution_result.get("data")
                    if data is None:
                        data = execution_result

                    if data and (isinstance(data, dict) or isinstance(data, str)):
                        if data and (data != {} and data != ""):
                            if task_matches_pipe_catalog(original_task, "dp.intent.pipe_weather"):
                                data_str = str(data).lower()
                                weather_indicators = catalog_pipe_tokens(
                                    "critic.pipe.weather_score_tokens"
                                )
                                if any(ind in data_str for ind in weather_indicators):
                                    logger.info(_te_t("te.log.weather_ok"))
                                    return {
                                        "completed": True,
                                        "remaining": "",
                                        "reason": _te_t("te.reason.weather_valid_data"),
                                    }
                                city = self._extract_city(original_task)
                                city_hint = city if city else _te_t("te.cityhint.example_beijing")
                                remaining = _te_t(
                                    "te.remaining.weather_skill_with_city_hint",
                                    city_hint=city_hint,
                                )
                                logger.warning(
                                    _te_t(
                                        "te.warn.weather_bad",
                                        snippet=data_str[:50],
                                        remaining=remaining,
                                    )
                                )
                                return {
                                    "completed": False,
                                    "remaining": remaining,
                                    "reason": _te_t("te.reason.weather_invalid_data"),
                                }
                            logger.info(_te_t("te.log.skill_ok"))
                            return {
                                "completed": True,
                                "remaining": "",
                                "reason": _te_t("te.reason.skill_data_ok"),
                            }

        if result_data and isinstance(result_data, dict):
            if "execution_result" in result_data:
                exec_err = result_data.get("execution_result")
            else:
                executor_data = result_data.get("executor", {})
                exec_err = executor_data.get("execution_result")
            if exec_err and isinstance(exec_err, dict) and exec_err.get("status") == "error":
                error_msg = exec_err.get("error", "")
                if task_matches_pipe_catalog(error_msg, "critic.pipe.city_required_errors"):
                    city = self._extract_city(original_task)
                    if city:
                        remaining = _te_t("te.remaining.weather_with_city", city=city)
                    else:
                        remaining = _te_t("te.remaining.city_required_short")
                    logger.info(_te_t("te.log.quick_err", err=error_msg, rem=remaining))
                    return {"completed": False, "remaining": remaining, "reason": error_msg}

        context_block = ""
        if previous_context:
            context_block = _te_t("te.llm.context_header") + str(previous_context) + "\n"
        prompt = _te_t(
            "te.llm.evaluate_prompt",
            original_task=original_task,
            current_result=str(current_result)[:3000],
            context_block=context_block,
        )
        try:
            response = await self.router.call_llm(prompt, brain_type="think", temperature=0.1)
            data = extract_json_from_llm_output(response)
            if data and "completed" in data:
                return data
            logger.warning(_te_t("te.warn.bad_eval_response", snippet=str(response)[:800]))
            return {
                "completed": True,
                "remaining": "",
                "reason": _te_t("te.reason.eval_fallback"),
            }
        except Exception as e:
            logger.error(_te_t("te.err.eval_failed", e=e))
            return {
                "completed": True,
                "remaining": "",
                "reason": _te_t("te.reason.eval_exception", detail=str(e)),
            }
