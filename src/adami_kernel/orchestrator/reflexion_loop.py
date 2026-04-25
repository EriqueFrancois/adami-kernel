# 文件路径：src/adami_kernel/orchestrator/reflexion_loop.py
# 版本：v2.8（AGL 统一由 observability.agl_compat 注入）
# 修改时间：2026-04-08

from __future__ import annotations

import json
import logging
import time
from collections import OrderedDict
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Dict, Optional

logger = logging.getLogger("AdamI-ReflexionLoop")

if TYPE_CHECKING:
    from adami_kernel.self_test.self_test_engine import SelfTestEngine
    from adami_kernel.skill_manager.skill_optimizer import SkillOptimizer

from adami_kernel.config import settings
from adami_kernel.i18n import t
from adami_kernel.observability.agl_compat import agl, get_trace_context
from adami_kernel.telemetry.experience_sink import get_experience_sink

# ====================== 【阶段4 新增】OpenTelemetry Span 覆盖（带安全回退） ======================
try:
    from adami_kernel.web.observability import observability
except Exception as e:
    logger.warning(
        t(
            "refl.warn.obs_import",
            locale=settings.effective_ui_default_locale(),
            e=e,
        )
    )

    @contextmanager
    def noop_start_span(*args, **kwargs):
        yield None

    observability = type("Observability", (), {"start_span": noop_start_span})()
# =================================================================================

from adami_kernel.cortex.router import LLMRouter
from adami_kernel.cortex.tools.json_parser import extract_json_from_llm_output
from adami_kernel.hippocampus.episodic_memory import EpisodicMemory
from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.nexus.bus import EventBus
from adami_kernel.nexus.event import AdamiEvent, EventPriority


def _refl_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class ReflexionLoop:
    """
    AdamI 2.0 Reflexion 自我反思闭环（工业级自愈引擎）
    核心流程：Recall（错题本检索）→ Critique（LLM 根因分析）→ Plan（生成修正计划）→ Act（执行重试）
    严格限制最大 3 次重试，失败后永久存入 episodic_memory 并暂停工作流等待人类介入
    【v2.8】：AGL 由 adami_kernel.observability.agl_compat 单点注入
    """

    def __init__(
        self,
        memory: LayeredMemory,
        episodic_memory: EpisodicMemory,
        router: LLMRouter,
        bus: EventBus,
    ):
        self.memory = memory
        self.episodic_memory = episodic_memory
        self.router = router
        self.bus = bus
        self.workflow_engine = None

        # 延迟导入，避免触发 OTEL 冲突链
        self.self_test_engine: Optional[SelfTestEngine] = None
        self.skill_optimizer: Optional[SkillOptimizer] = None

        self.last_full_test_time: OrderedDict = OrderedDict()
        self._reflexion_counter = 0

        self.max_retries = 3
        logger.info(_refl_t("refl.log.ready"))

    def set_self_test_engine(self, self_test_engine):
        """延迟注入 SelfTestEngine"""
        self.self_test_engine = self_test_engine
        logger.debug(_refl_t("refl.debug.selftest_set"))

    def set_skill_optimizer(self, skill_optimizer):
        """延迟注入 SkillOptimizer"""
        self.skill_optimizer = skill_optimizer
        logger.debug(_refl_t("refl.debug.optimizer_set"))

    def _prune_old_test_times(self):
        now = time.time()
        cutoff = now - 3600
        to_remove = [k for k, v in list(self.last_full_test_time.items()) if v < cutoff]
        for k in to_remove:
            self.last_full_test_time.pop(k)
        if to_remove:
            logger.debug(_refl_t("refl.debug.prune_times", n=len(to_remove)))

    async def optimize_skill(self, skill_name: str) -> Dict[str, Any]:
        if not self.skill_optimizer:
            logger.warning(_refl_t("refl.warn.opt_missing", name=skill_name))
            return {"status": "error", "reason": _refl_t("refl.optimizer.not_ready")}
        logger.info(_refl_t("refl.log.opt_req", name=skill_name))
        result = await self.skill_optimizer.optimize(skill_name)
        return result

    async def trigger_reflexion(
        self, workflow_id: str, chat_id: str, failure_context: Dict[str, Any]
    ) -> bool:
        with get_trace_context(
            trace_id=f"reflexion_{workflow_id}",
            task_description=failure_context.get(
                "task_description", _refl_t("refl.default.unknown_task")
            ),
            metadata={"chat_id": chat_id, "workflow_id": workflow_id},
        ) as trace:
            logger.info(_refl_t("refl.log.heal_start", wid=workflow_id))

            if self.self_test_engine:
                logger.info(_refl_t("refl.log.after_fail_selftest"))
                test_report = await self.self_test_engine.run_critical_tests(
                    workflow_id=workflow_id, chat_id=chat_id
                )

                reward = test_report.get("pass_rate", 0.0)
                agl.emit_reward(
                    trace_id=trace.trace_id,
                    reward=reward,
                    metadata={"status": test_report.get("status"), "workflow_id": workflow_id},
                )
                get_experience_sink().record_feedback(
                    trace_id=trace.trace_id,
                    reward=reward,
                    metadata={
                        "status": test_report.get("status"),
                        "workflow_id": workflow_id,
                    },
                    source="reflexion_loop.self_test",
                )

                if test_report.get("status") == "failed":
                    logger.warning(_refl_t("refl.warn.selftest_fail", rate=reward))
                    await self._pause_workflow(
                        workflow_id,
                        chat_id,
                        _refl_t("refl.pause.selftest_failed", reward=reward),
                    )
                    return False

                elif test_report.get("status") == "error":
                    logger.warning(_refl_t("refl.warn.selftest_err"))
                else:
                    logger.info(_refl_t("refl.log.selftest_ok", rate=reward))

            self._reflexion_counter += 1
            if self._reflexion_counter % 100 == 0:
                self._prune_old_test_times()

            retry_count = 0
            while retry_count < self.max_retries:
                retry_count += 1
                logger.info(_refl_t("refl.log.loop_n", cur=retry_count, mx=self.max_retries))

                try:
                    history_lessons = await self._recall_lessons(failure_context)
                    critique = await self._critique_failure(failure_context, history_lessons)

                    # 写入 Dashboard 数据源（reflexion_logs）
                    # Dashboard /api/reflexion_logs 读取 LayeredMemory.get_reflexion_logs()
                    try:
                        await self.memory.save_reflexion_log(
                            workflow_id=workflow_id,
                            root_cause=str(
                                critique.get("root_cause", _refl_t("refl.default.unknown"))
                            ),
                            suggested_action=str(
                                critique.get("suggested_action", _refl_t("refl.default.retry_task"))
                            ),
                            confidence=float(critique.get("confidence", 0.5) or 0.5),
                            chat_id=chat_id or "system",
                        )
                    except Exception as e:
                        logger.warning(_refl_t("refl.warn.log_write", e=e))

                    plan = await self._generate_plan(critique, failure_context)
                    success = await self._execute_plan(plan, workflow_id, chat_id)

                    if success:
                        logger.info(_refl_t("refl.log.heal_ok", wid=workflow_id))
                        return True

                except Exception as e:
                    logger.error(
                        _refl_t("refl.err.round_exc", n=retry_count, e=e),
                        exc_info=True,
                    )

            await self.episodic_memory.save_error(
                task_description=failure_context.get(
                    "task_description", _refl_t("refl.default.unknown_task")
                ),
                action=failure_context.get("action", "UNKNOWN"),
                args=str(failure_context.get("args", {})),
                error=str(failure_context.get("error", _refl_t("refl.default.unknown_error"))),
            )

            await self._pause_workflow(workflow_id, chat_id, _refl_t("refl.pause.hitl_exhausted"))

            logger.warning(_refl_t("refl.warn.exhausted", wid=workflow_id))
            return False

    async def _pause_workflow(self, workflow_id: str, chat_id: str, reason: str):
        try:
            from adami_kernel.orchestrator.hitl_handler import hitl_handler

            if hitl_handler:
                await hitl_handler.trigger_paused(workflow_id, chat_id, reason)
                logger.info(_refl_t("refl.log.pause_hitl", wid=workflow_id))
                return
        except Exception as e:
            logger.warning(_refl_t("refl.warn.pause_hitl_fail", e=e))

        event = AdamiEvent(
            trace_id=f"reflexion_pause_{workflow_id}",
            source_module="reflexion_loop",
            target_topic="system.events",
            priority=EventPriority.HIGH,
            payload={
                "workflow_id": workflow_id,
                "chat_id": chat_id,
                "status": "PAUSED",
                "reason": reason,
            },
        )
        await self.bus.publish(event)
        logger.info(_refl_t("refl.log.pause_bus", wid=workflow_id))

    async def _recall_lessons(self, failure_context: Dict[str, Any]) -> list:
        with observability.start_span("reflexion.recall_lessons", attributes=failure_context):
            query = (
                failure_context.get("task_description", "")
                + " "
                + str(failure_context.get("error", ""))
            )
            lessons = await self.episodic_memory.recall_errors(query, "reflexion")
            return lessons[:3]

    async def _critique_failure(
        self, failure_context: Dict[str, Any], history_lessons: list
    ) -> Dict[str, Any]:
        with observability.start_span("reflexion.critique_failure"):
            prompt = _refl_t(
                "refl.prompt.critique",
                task_description=failure_context.get(
                    "task_description", _refl_t("refl.default.unknown_task")
                ),
                error=failure_context.get("error", _refl_t("refl.default.unknown_error")),
                history_json=json.dumps(history_lessons, ensure_ascii=False),
            )
            raw = await self.router.call_llm(prompt=prompt, brain_type="think", temperature=0.0)
            extracted = extract_json_from_llm_output(raw)
            return extracted or {
                "root_cause": _refl_t("refl.default.unknown"),
                "suggested_action": _refl_t("refl.default.retry_task"),
                "confidence": 0.5,
                "new_config": {},
            }

    async def _generate_plan(
        self, critique: Dict[str, Any], failure_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        with observability.start_span("reflexion.generate_plan"):
            return {
                "action": critique.get("suggested_action", _refl_t("refl.default.retry_node")),
                "node_id": failure_context.get("node_id"),
                "new_config": critique.get("new_config", {}),
                "confidence": critique.get("confidence", 0.5),
            }

    async def _execute_plan(self, plan: Dict[str, Any], workflow_id: str, chat_id: str) -> bool:
        with observability.start_span(
            span_name="reflexion.execute_plan", workflow_id=workflow_id, chat_id=chat_id
        ):
            if not self.workflow_engine:
                logger.error(_refl_t("refl.err.no_wf_engine"))
                return False

            action = plan.get("action", "").lower()
            node_id = plan.get("node_id")

            if action == "retry" and node_id:
                success = await self.workflow_engine.retry_node(workflow_id, node_id, chat_id)
                logger.info(_refl_t("refl.log.retry_node", nid=node_id, ok=success))
                return success

            elif action == "modify_config" and node_id:
                success = await self.workflow_engine.modify_node_config(
                    workflow_id, node_id, plan.get("new_config", {}), chat_id
                )
                logger.info(_refl_t("refl.log.modify_cfg", ok=success))
                return success

            elif action == "skip" and node_id:
                success = await self.workflow_engine.skip_node(workflow_id, node_id, chat_id)
                logger.info(_refl_t("refl.log.skip", ok=success))
                return success

            else:
                logger.warning(_refl_t("refl.warn.unknown_action", action=action))
                return False
