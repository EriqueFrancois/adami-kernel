# --- START OF FILE critic.py ---

import json
import logging
from typing import Any

from adami_kernel.config import settings
from adami_kernel.cortex.router import LLMRouter
from adami_kernel.cortex.tools.json_parser import extract_json_from_llm_output
from adami_kernel.hippocampus.episodic_memory import EpisodicMemory
from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.i18n import t
from adami_kernel.i18n.ui_static import catalog_pipe_tokens, task_matches_pipe_catalog
from adami_kernel.orchestrator.agent_models import AgentFeedback, AgentMessage, AgentRole

logger = logging.getLogger("AdamI-Critic")


def _crt_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


def calculate_quality_score(data: Any, task_description: str) -> float:
    """
    根据任务描述和数据内容计算质量分数（0-100）。
    分数越高表示数据质量越好。
    """
    if data is None:
        return 0.0
    data_str = str(data).lower()
    score = 0.0

    td = task_description or ""
    keywords: tuple[str, ...] = ()
    if task_matches_pipe_catalog(td, "dp.intent.pipe_weather"):
        keywords = catalog_pipe_tokens("critic.pipe.weather_score_tokens")
    elif task_matches_pipe_catalog(td, "planner.pipe.crypto_param_hints"):
        keywords = catalog_pipe_tokens("critic.pipe.price_score_tokens")

    if keywords:
        matched = sum(1 for kw in keywords if kw in data_str)
        score = min(100, matched * 20)  # 每个匹配关键词给20分，最多100
    else:
        markers = tuple(
            m.lower() if m.isascii() else m
            for m in catalog_pipe_tokens("critic.pipe.empty_score_markers")
        )
        if data_str and data_str not in markers:
            score = 80.0
        else:
            score = 20.0

    if not data_str:
        score = 0.0

    return score


class Critic:
    def __init__(self, memory: LayeredMemory, episodic_memory: EpisodicMemory, router: LLMRouter):
        self.memory = memory
        self.episodic_memory = episodic_memory
        self.router = router
        logger.info(_crt_t("crt.log.ready"))

    async def process(self, msg: AgentMessage) -> AgentMessage:
        if msg.message_type != "task":
            return AgentMessage(
                source_agent=AgentRole.CRITIC,
                target_agent=AgentRole.ORCHESTRATOR,
                message_type="error",
                payload={"error": t("eng.error.not_task")},
                workflow_id=msg.workflow_id,
                chat_id=msg.chat_id,
            )

        task = msg.payload.get("task", {})
        previous_result = msg.payload.get("result", {})
        task_description = task.get("description", "")

        logger.info(_crt_t("crt.log.review_start", snippet=task_description[:80]))

        try:
            executor_data = previous_result.get("executor", {})
            execution_result = executor_data.get("execution_result")

            logger.info(_crt_t("crt.log.exec_result", data=str(execution_result)[:2000]))
            logger.info(_crt_t("crt.log.task_desc", data=str(task_description)[:2000]))

            quality_score = 0.0

            if execution_result and isinstance(execution_result, dict):
                if execution_result.get("status") == "success":
                    data = execution_result.get("data")
                    if data is None:
                        data = execution_result
                        logger.debug(_crt_t("crt.debug.data_fallback"))

                    quality_score = calculate_quality_score(data, task_description)
                    logger.info(_crt_t("crt.log.quality", score=f"{quality_score:.2f}"))

                    is_valid = True
                    reject_reason = None

                    if task_matches_pipe_catalog(task_description, "dp.intent.pipe_weather"):
                        if data is None:
                            is_valid = False
                            reject_reason = t("critic.reject.data_empty")
                        else:
                            data_str = str(data).lower()
                            weather_indicators = catalog_pipe_tokens(
                                "critic.pipe.weather_score_tokens"
                            )
                            if not any(ind in data_str for ind in weather_indicators):
                                is_valid = False
                                reject_reason = t(
                                    "critic.reject.weather_invalid",
                                    preview=data_str[:100],
                                )
                                quality_score = 0.0

                    if not is_valid:
                        logger.warning(_crt_t("crt.warn.reject", reason=reject_reason or ""))
                        feedback = AgentFeedback(
                            approved=False,
                            feedback=t("critic.feedback.invalid_data", reason=reject_reason or ""),
                            suggestions=[t("critic.suggestion.check_weather_api")],
                            retry_count=0,
                        )
                        feedback_dict = feedback.model_dump()
                        feedback_dict["quality_score"] = quality_score
                        await self.memory.store_experience(
                            trace_id=msg.trace_id,
                            domain=f"critic_{msg.chat_id}",
                            payload=feedback_dict,
                            chat_id=msg.chat_id,
                        )
                        return AgentMessage(
                            source_agent=AgentRole.CRITIC,
                            target_agent=AgentRole.ORCHESTRATOR,
                            message_type="feedback",
                            payload={"feedback": feedback_dict},
                            workflow_id=msg.workflow_id,
                            chat_id=msg.chat_id,
                        )

                    feedback = AgentFeedback(
                        approved=True,
                        feedback=t("critic.feedback.approved_ok"),
                        suggestions=[],
                        retry_count=0,
                    )
                    logger.info(_crt_t("crt.log.approve_direct"))
                    feedback_dict = feedback.model_dump()
                    feedback_dict["quality_score"] = quality_score
                    await self.memory.store_experience(
                        trace_id=msg.trace_id,
                        domain=f"critic_{msg.chat_id}",
                        payload=feedback_dict,
                        chat_id=msg.chat_id,
                    )
                    return AgentMessage(
                        source_agent=AgentRole.CRITIC,
                        target_agent=AgentRole.ORCHESTRATOR,
                        message_type="feedback",
                        payload={"feedback": feedback_dict},
                        workflow_id=msg.workflow_id,
                        chat_id=msg.chat_id,
                    )

                elif execution_result.get("status") == "error":
                    error_msg = execution_result.get("error", "")
                    if task_matches_pipe_catalog(error_msg, "critic.pipe.city_required_errors"):
                        logger.warning(_crt_t("crt.warn.exec_fail_reject", msg=error_msg))
                        feedback = AgentFeedback(
                            approved=False,
                            feedback=t("critic.feedback.exec_failed_city", error_msg=error_msg),
                            suggestions=[t("critic.suggestion.check_city_extraction")],
                            retry_count=0,
                        )
                        feedback_dict = feedback.model_dump()
                        feedback_dict["quality_score"] = 0.0
                        await self.memory.store_experience(
                            trace_id=msg.trace_id,
                            domain=f"critic_{msg.chat_id}",
                            payload=feedback_dict,
                            chat_id=msg.chat_id,
                        )
                        return AgentMessage(
                            source_agent=AgentRole.CRITIC,
                            target_agent=AgentRole.ORCHESTRATOR,
                            message_type="feedback",
                            payload={"feedback": feedback_dict},
                            workflow_id=msg.workflow_id,
                            chat_id=msg.chat_id,
                        )
                    logger.warning(_crt_t("crt.warn.exec_error_llm", msg=error_msg))

            error_recall = (
                await self.episodic_memory.recall_errors(task_description, "critic_review")
                if self.episodic_memory
                else ""
            )

            execution_section = ""
            if execution_result:
                execution_section = (
                    "\n\n"
                    + t("critic.llm.section_execution")
                    + "\n"
                    + json.dumps(execution_result, ensure_ascii=False, indent=2)
                )

            review_prompt = t(
                "critic.llm.review_prompt",
                task_description=task_description,
                schema_json=json.dumps(
                    task.get("required_output_schema", {}), ensure_ascii=False, indent=2
                ),
                error_recall=error_recall,
                previous_result_json=json.dumps(previous_result, ensure_ascii=False, indent=2),
                execution_section=execution_section,
            )

            raw_response = await self.router.call_llm(
                prompt=review_prompt, brain_type="think", temperature=0.2
            )

            extracted = extract_json_from_llm_output(raw_response)
            if extracted is None:
                logger.warning(_crt_t("crt.warn.no_json"))
                feedback = AgentFeedback(
                    approved=False, feedback=t("critic.feedback.json_parse_fail")
                )
                quality_score = 0.0
            else:
                try:
                    feedback = AgentFeedback.model_validate(extracted, strict=False)
                    quality_score = extracted.get("quality_score", 0.0)
                except Exception as validate_e:
                    logger.warning(_crt_t("crt.warn.validate_fail", e=validate_e))
                    feedback = AgentFeedback(
                        approved=False,
                        feedback=t("critic.feedback.validate_fail", detail=str(validate_e)),
                    )
                    quality_score = 0.0

            feedback_dict = feedback.model_dump()
            feedback_dict["quality_score"] = quality_score
            await self.memory.store_experience(
                trace_id=msg.trace_id,
                domain=f"critic_{msg.chat_id}",
                payload=feedback_dict,
                chat_id=msg.chat_id,
            )

            return AgentMessage(
                source_agent=AgentRole.CRITIC,
                target_agent=AgentRole.ORCHESTRATOR,
                message_type="feedback",
                payload={"feedback": feedback_dict},
                workflow_id=msg.workflow_id,
                chat_id=msg.chat_id,
            )

        except Exception as e:
            logger.error(_crt_t("crt.err.review", e=e), exc_info=True)
            return AgentMessage(
                source_agent=AgentRole.CRITIC,
                target_agent=AgentRole.ORCHESTRATOR,
                message_type="error",
                payload={"error": str(e)},
                workflow_id=msg.workflow_id,
                chat_id=msg.chat_id,
            )


# --- END OF FILE critic.py ---
