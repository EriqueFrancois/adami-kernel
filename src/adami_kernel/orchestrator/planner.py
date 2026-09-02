# 文件路径：src/adami_kernel/orchestrator/planner.py
# 版本：v2.6（步骤4：Compose 工作流经 EventBus WORKFLOW_START → WorkflowEngine 执行）
# 修改时间：2026-04-08

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

from adami_kernel.config import mcp_agent_planner_pilot_effective, settings
from adami_kernel.cortex.intent_adaptive.handoff_meta import build_prior_intent_guess_english_line

# ====================== 【Bug 12 核心修复】使用公共 JSON 解析器 ======================
from adami_kernel.cortex.tools.json_parser import extract_json_from_llm_output

# =================================================================================
from adami_kernel.hippocampus.episodic_memory import EpisodicMemory
from adami_kernel.i18n import t
from adami_kernel.i18n.ui_static import catalog_pipe_tokens, task_matches_pipe_catalog
from adami_kernel.nexus.event import AdamiEvent, EventPriority
from adami_kernel.orchestrator import planner_prompts as _pp
from adami_kernel.orchestrator.long_task_schema import (
    LongTaskPhase,
    StageArtifact,
    append_stage_artifact,
    maybe_initialize_long_task_context,
    sha256_hex_of_utf8,
)

# =================================================================================
# ====================== 【2.0 阶段2】MultiAgentOrchestrator 支持 ======================
from adami_kernel.orchestrator.multi_agent_orchestrator import MultiAgentOrchestrator

# =================================================================================
# ====================== 【2.0 阶段3 新增】ReflexionLoop + TDDEvolution ======================
from adami_kernel.orchestrator.reflexion_loop import ReflexionLoop

# =================================================================================
# ====================== 【新增】SkillComposer ======================
from adami_kernel.orchestrator.skill_composer import SkillComposer

# =================================================================================
# ====================== 【新增】任务评估器 ======================
from adami_kernel.orchestrator.task_evaluator import TaskEvaluator
from adami_kernel.orchestrator.tdd_evolution import TDDEvolution

# =================================================================================
# ====================== 【2.0 阶段1】WorkflowEngine 支持 ======================
from adami_kernel.orchestrator.workflow_engine import WorkflowEngine
from adami_kernel.orchestrator.workflow_models import WorkflowState, create_initial_workflow_state
from adami_kernel.skill_manager.skill_router import SkillRouter

logger = logging.getLogger("AdamI-Planner")

if TYPE_CHECKING:
    from adami_kernel.hippocampus.layered_memory import LayeredMemory
    from adami_kernel.orchestrator.skill_composer import SkillComposer
    from adami_kernel.orchestrator.tdd_evolution import TDDEvolution
    from adami_kernel.orchestrator.workflow_engine import WorkflowEngine
    from adami_kernel.skill_manager.skill_router import SkillRouter


def _plnr_t(key: str, **kwargs: Any) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class TaskPlanner:
    """
    AdamI 任务规划器 V3.0（迭代式任务执行与评估 + Step 4 扩展：Graceful Degradation 成功率长期监控）
    【v2.4 核心修复】：SkillMetadata 兼容 + 错误结果安全切片 + 参数提取强化（避免会议纪要误解析）
    """

    def __init__(
        self,
        router,
        evolution_engine,
        bus,
        sensitive_filter,
        episodic_memory: EpisodicMemory = None,
        memory: LayeredMemory = None,
        workflow_engine: WorkflowEngine = None,
        multi_agent_orchestrator: "MultiAgentOrchestrator" = None,
        reflexion_loop: "ReflexionLoop" = None,
        tdd_evolution: TDDEvolution = None,
        skill_composer: SkillComposer = None,
        skill_router: SkillRouter = None,
        second_brain: Any = None,
    ):
        self.router = router
        self.evolution_engine = evolution_engine
        self.bus = bus
        self.sensitive_filter = sensitive_filter
        self.episodic_memory = episodic_memory
        self.memory = memory
        self.second_brain = second_brain

        self.workflow_engine = workflow_engine
        self.multi_agent_orchestrator = multi_agent_orchestrator
        self.reflexion_loop = reflexion_loop
        self.tdd_evolution = tdd_evolution
        self.skill_composer = skill_composer
        self.skill_router = skill_router

        self.evaluator = TaskEvaluator(router) if router else None
        self._skillrouter_skillmetadata_name_warned = False

        # ====================== 【Step 4 扩展】Graceful Degradation 成功率长期监控 ======================
        self.degradation_stats: Dict[str, Any] = {
            "total_attempts": 0,  # 总生成尝试次数
            "graceful_degrades": 0,  # Tier1 GitHub 超时降级次数
            "tier1_success": 0,  # GitHub Tier1 成功次数
            "llm_fallbacks": 0,  # LLM Tier2 回退次数
            "last_report_time": None,
        }
        logger.debug(_plnr_t("plnr.debug.degrade_init"))
        # =================================================================================================

        logger.info(_plnr_t("plnr.log.ready"))

    async def initialize(self):
        """2.0 初始化所有引擎"""
        if self.memory is None:
            logger.warning(_plnr_t("plnr.warn.no_memory"))
            return

        if self.workflow_engine is None:
            self.workflow_engine = WorkflowEngine(
                self.bus, self.memory, self.evolution_engine.toolbox
            )
            await self.workflow_engine.initialize()
            logger.debug(_plnr_t("plnr.debug.wf_created"))
        else:
            logger.debug(_plnr_t("plnr.debug.wf_injected"))

        if self.multi_agent_orchestrator is None:
            self.multi_agent_orchestrator = MultiAgentOrchestrator(
                self.bus, self.memory, self.evolution_engine.toolbox
            )
            await self.multi_agent_orchestrator.initialize()
            logger.debug(_plnr_t("plnr.debug.mag_created"))
        else:
            logger.debug(_plnr_t("plnr.debug.mag_injected"))

        if self.reflexion_loop is None:
            self.reflexion_loop = ReflexionLoop(
                self.memory, self.episodic_memory, self.router, self.bus
            )
        if self.tdd_evolution is None:
            self.tdd_evolution = TDDEvolution(
                self.evolution_engine, None, self.memory, self.episodic_memory
            )
        logger.debug(_plnr_t("plnr.debug.refl_wired"))

        if self.skill_composer is None:
            if hasattr(self.evolution_engine, "toolbox"):
                self.skill_composer = SkillComposer(
                    self.router, self.memory, self.evolution_engine.toolbox
                )
                logger.debug(_plnr_t("plnr.debug.sc_created"))
            else:
                logger.warning(_plnr_t("plnr.warn.sc_no_toolbox"))
        else:
            logger.debug(_plnr_t("plnr.debug.sc_injected"))

    # ====================== 【Step 4 新增】降级统计记录与报告 ======================
    async def _record_degradation_stat(self, tier1_success: bool = False, degraded: bool = False):
        """记录一次生成尝试的降级统计，并持久化到 LayeredMemory"""
        self.degradation_stats["total_attempts"] += 1
        if tier1_success:
            self.degradation_stats["tier1_success"] += 1
        if degraded:
            self.degradation_stats["graceful_degrades"] += 1
        else:
            self.degradation_stats["llm_fallbacks"] += 1

        # 每 5 次尝试自动报告一次成功率
        if self.degradation_stats["total_attempts"] % 5 == 0:
            await self._report_degradation_stats()

    async def _report_degradation_stats(self):
        """生成并持久化降级成功率报告（长期监控）"""
        total = self.degradation_stats["total_attempts"]
        degrades = self.degradation_stats["graceful_degrades"]
        tier1_ok = self.degradation_stats["tier1_success"]
        success_rate = round((tier1_ok / total) * 100, 2) if total > 0 else 0.0
        degrade_rate = round((degrades / total) * 100, 2) if total > 0 else 0.0

        report = {
            "timestamp": datetime.now().isoformat(),
            "total_attempts": total,
            "tier1_success": tier1_ok,
            "graceful_degrades": degrades,
            "llm_fallbacks": self.degradation_stats["llm_fallbacks"],
            "tier1_success_rate": success_rate,
            "graceful_degrade_rate": degrade_rate,
            "note": t("planner.monitor.degrade_note"),
        }

        logger.info(
            _plnr_t(
                "plnr.log.degrade_report",
                total=total,
                r1=success_rate,
                r2=degrade_rate,
            )
        )

        # 持久化到 LayeredMemory（长期监控）
        if self.memory:
            await self.memory.store_experience(
                trace_id="degradation_stats",
                domain="planner_degradation_monitor",
                payload=report,
                chat_id="system",
            )
        self.degradation_stats["last_report_time"] = datetime.now().isoformat()

    # =================================================================================================

    async def _execute_composed_workflow_via_bus(self, workflow_state: WorkflowState) -> Any:
        """将 SkillComposer 产出的 WorkflowState 落盘，经 workflow.events / WORKFLOW_START 交由引擎执行并等待收口。"""
        if not self.workflow_engine or not self.bus:
            raise RuntimeError(t("planner.error.workflow_not_ready"))
        if self.memory:
            await self.memory.save_workflow_state(workflow_state)
        future = await self.workflow_engine.prepare_composed_workflow_for_bus(workflow_state)
        await self.bus.publish(
            AdamiEvent(
                trace_id=f"wf_start_{workflow_state.workflow_id}",
                source_module="planner",
                target_topic="workflow.events",
                priority=EventPriority.NORMAL,
                payload={
                    "workflow_id": workflow_state.workflow_id,
                    "event_type": "WORKFLOW_START",
                    "chat_id": workflow_state.chat_id,
                },
            )
        )
        return await future

    async def _schedule_digest_note_task(
        self,
        *,
        note_path: str,
        trace_id: str,
        chat_id: str,
        source: str,
    ) -> None:
        """
        最小闭环：将 note_path 内容（截断）打包成一个后续 planner 任务，发布到 system.events。
        同时写入一个 WorkflowState StageArtifact（file:// URI），形成可回放链路锚点。
        """
        if not self.bus:
            return

        p = Path(str(note_path)).expanduser()
        try:
            uri = p.resolve().as_uri()
        except Exception:
            uri = f"file://{p}"

        body = ""
        try:
            if p.is_file():
                body = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            body = ""
        if len(body) > 12_000:
            body = body[:12_000] + t("planner.digest.body_truncated")

        # StageArtifact: anchor the note as research output.
        try:
            wf = create_initial_workflow_state(
                chat_id=str(chat_id), task_description="digest_second_brain_note"
            )
            maybe_initialize_long_task_context(wf)
            append_stage_artifact(
                wf,
                StageArtifact(
                    phase=LongTaskPhase.RESEARCH,
                    artifact_type="second_brain_note",
                    uri_or_payload_ref=uri,
                    summary=f"digest target: {uri}",
                    producer_agent="planner.last30days_digest",
                    content_hash=sha256_hex_of_utf8(uri),
                ),
                set_current_phase=False,
            )
            if self.memory:
                await self.memory.save_workflow_state(wf)
        except Exception as e:
            logger.debug(_plnr_t("plnr.debug.digest_skip", e=e))

        task = _pp.DIGEST_NOTE_TASK.format(
            source=source,
            note_path=note_path,
            uri=uri,
            body=body or _pp.EMPTY_NOTE_BODY,
        )
        ev = AdamiEvent(
            trace_id=f"{trace_id}_digest_note",
            source_module="planner",
            target_topic="system.events",
            priority=EventPriority.NORMAL,
            payload={"task": task, "chat_id": str(chat_id)},
        )
        await self.bus.publish(ev)

    async def plan_and_execute(
        self,
        task: str,
        trace_id: str,
        chat_id: int = None,
        *,
        intent_adaptive_meta: Optional[Dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        迭代式任务执行：重复执行、评估，直到任务完成或达到最大次数
        【v2.4 核心修复】：SkillRouter 兼容 + 错误结果安全切片
        """
        logger.info(_plnr_t("plnr.log.iter_start", snippet=task[:80]))

        def _out(
            text: Any,
            *,
            status: str = "success",
            workflow_id: Optional[str] = None,
        ) -> dict[str, Any]:
            """Normalized Planner output schema (Milestone A lifecycle contract).

            Always returns a dict: {text, trace_id, workflow_id, status}.
            """
            wid = str(workflow_id or "").strip()
            return {
                "text": str(text) if text is not None else "",
                "trace_id": str(trace_id),
                "workflow_id": wid,
                "status": str(status or "success"),
            }

        if intent_adaptive_meta:
            try:
                dumped = json.dumps(intent_adaptive_meta, ensure_ascii=False, default=str)
            except Exception:
                dumped = str(intent_adaptive_meta)
            if len(dumped) > 800:
                dumped = dumped[:800] + "…"
            logger.debug("[intent_adaptive_handoff] meta=%s", dumped)
        chat_id_str = str(chat_id) if chat_id else "default"

        # ====================== SkillRouter 单点意图早检（技能创建）======================
        if self.skill_router and self.skill_router.is_skill_creation_task(task):
            logger.info(_plnr_t("plnr.log.unified_create"))
            await self._record_degradation_stat(tier1_success=False)

            use_wf_for_create = getattr(settings, "ADAMI_SKILL_CREATION_USE_WORKFLOW_ENGINE", True)
            if use_wf_for_create and self.workflow_engine and self.skill_composer:
                try:
                    all_skills = (
                        self.evolution_engine.get_all_skills()
                        if self.evolution_engine
                        and hasattr(self.evolution_engine, "get_all_skills")
                        else []
                    )
                    skill_names = [s["name"] for s in all_skills] if all_skills else []
                    workflow_state = await self.skill_composer.compose_workflow(task, skill_names)
                    if workflow_state and isinstance(workflow_state, WorkflowState):
                        workflow_state.chat_id = chat_id_str
                        workflow_state.context["original_user_task"] = task
                        logger.info(_plnr_t("plnr.log.unified_wf"))
                        result = await self._execute_composed_workflow_via_bus(workflow_state)
                        if isinstance(result, dict):
                            await self._report_degradation_stats()
                            return _out(
                                self._format_result(result),
                                status=str(result.get("status") or "success"),
                                workflow_id=workflow_state.workflow_id,
                            )
                        await self._report_degradation_stats()
                        return _out(str(result), status="success", workflow_id=workflow_state.workflow_id)
                    logger.warning(_plnr_t("plnr.warn.unified_no_wfstate"))
                except Exception as e:
                    logger.warning(
                        _plnr_t("plnr.warn.unified_wf_fail", e=e),
                        exc_info=True,
                    )

            if not self.multi_agent_orchestrator:
                return _out(t("planner.skill_create.path_unavailable"), status="error")
            logger.info(_plnr_t("plnr.log.unified_mag"))
            try:
                future = await self.multi_agent_orchestrator.start_multi_agent_workflow(
                    chat_id=chat_id_str,
                    task_description=task,
                    initial_context={"original_user_task": task},
                )
                result = await future
                if isinstance(result, dict):
                    formatted = self._format_result(result)
                    await self._report_degradation_stats()
                    return _out(
                        formatted,
                        status=str(result.get("status") or "success"),
                        workflow_id=str(result.get("workflow_id") or ""),
                    )
                await self._report_degradation_stats()
                return _out(str(result), status="success")
            except Exception as e:
                error_detail = str(e)
                friendly_msg = t("planner.skill_create.failed_with_detail", detail=error_detail)
                logger.error(_plnr_t("plnr.err.unified_mag", detail=error_detail))
                return _out(friendly_msg, status="error")
        # =================================================================================

        MAX_ITERATIONS = getattr(settings, "ADAMI_COMPLEX_TASK_MAX_RETRIES", 5)
        iteration = 0
        current_task = task
        context: Dict[str, Any] = {"original_user_task": task}
        if intent_adaptive_meta:
            context["intent_adaptive_meta"] = intent_adaptive_meta
            _prior = build_prior_intent_guess_english_line(intent_adaptive_meta)
            if _prior:
                context["intent_adaptive_prior_line"] = _prior
        final_result = None
        last_remaining = None

        while iteration < MAX_ITERATIONS:
            iteration += 1
            logger.info(
                _plnr_t(
                    "plnr.log.iter_round",
                    n=iteration,
                    snippet=current_task[:80],
                )
            )

            try:
                result = await self._execute_single_iteration(
                    current_task, trace_id, chat_id_str, context
                )
            except Exception as e:
                logger.error(_plnr_t("plnr.err.iter_exec", n=iteration, e=e), exc_info=True)
                result = t("planner.iteration.exec_failed", detail=str(e))

            if task_matches_pipe_catalog(str(result), "planner.pipe.iteration_abort_keywords"):
                logger.warning(_plnr_t("plnr.warn.iter_abort", snippet=str(result)[:200]))
                final_result = result
                break

            if not self.evaluator:
                logger.warning(_plnr_t("plnr.warn.no_evaluator"))
                final_result = result
                break

            eval_res = await self.evaluator.evaluate(task, result, context)
            completed = eval_res.get("completed", False)

            if completed:
                final_result = result
                logger.info(_plnr_t("plnr.log.iter_done", n=iteration))
                break
            else:
                remaining = eval_res.get("remaining", "").strip()
                if not remaining:
                    remaining = t("planner.evaluator.remaining_fallback")
                if remaining == last_remaining:
                    logger.warning(_plnr_t("plnr.warn.iter_stuck"))
                    final_result = result
                    break
                last_remaining = remaining
                current_task = remaining
                context["previous_result"] = result
                context["remaining_task"] = remaining
                context["iteration"] = iteration
                logger.info(_plnr_t("plnr.log.iter_next", task=current_task))

        if final_result:
            formatted = self._format_result(final_result)
            status_val = "success"
            if isinstance(final_result, dict):
                status_val = str(final_result.get("status") or "success")
            return _out(formatted, status=status_val)
        else:
            return _out(t("planner.task.incomplete"), status="incomplete")

    def _extract_result_from_context(self, context: Dict) -> str:
        """
        从工作流返回的 context 字典中提取最终结果（如天气数据、价格等）。
        支持递归搜索任意节点中的 data 字段，优先返回成功数据，否则返回错误信息。
        """
        executor_result = context.get("executor", {})
        if isinstance(executor_result, dict):
            execution_result = executor_result.get("execution_result")
            if isinstance(execution_result, dict):
                if execution_result.get("status") == "success":
                    data = execution_result.get("data")
                    if data:
                        return str(data)
                elif execution_result.get("status") == "error":
                    err = execution_result.get("error") or t("planner.result.unknown_error")
                    return t("planner.result.exec_error", detail=err)

        researcher_result = context.get("researcher", {})
        if isinstance(researcher_result, dict):
            summary = researcher_result.get("summary")
            if summary:
                return str(summary)

        def search_node(obj):
            if isinstance(obj, dict):
                if obj.get("status") == "success" and "data" in obj:
                    return obj["data"]
                for key, value in obj.items():
                    if key in ["result", "execution_result", "data", "response"]:
                        result = search_node(value)
                        if result:
                            return result
                    else:
                        result = search_node(value)
                        if result:
                            return result
            elif isinstance(obj, list):
                for item in obj:
                    result = search_node(item)
                    if result:
                        return result
            return None

        found_data = search_node(context)
        if found_data:
            return str(found_data)

        def search_error(obj):
            if isinstance(obj, dict):
                if obj.get("status") == "error" and "error" in obj:
                    return obj["error"]
                for v in obj.values():
                    err = search_error(v)
                    if err:
                        return err
            elif isinstance(obj, list):
                for item in obj:
                    err = search_error(item)
                    if err:
                        return err
            return None

        error_msg = search_error(context)
        if error_msg:
            return t("planner.result.task_failed", detail=error_msg)

        return t("planner.result.no_valid_result")

    def _format_result(self, result: Any) -> str:
        """
        统一格式化最终结果，支持字符串（可能是 JSON）或字典。
        """
        if isinstance(result, dict):
            # 【新增】直接处理技能返回的基础结构
            if "status" in result:
                if result["status"] == "success":
                    return str(result.get("data", t("planner.result.exec_success")))
                elif result["status"] == "error":
                    err = result.get("error") or t("planner.result.unknown_error")
                    return t("planner.result.task_issue", detail=err)
            return self._extract_result_from_context(result)
        elif isinstance(result, str):
            try:
                data = json.loads(result)
                if isinstance(data, dict):
                    return self._extract_result_from_context(data)
                else:
                    return result
            except json.JSONDecodeError:
                return result
        else:
            return str(result)

    async def _execute_single_iteration(
        self, task: str, trace_id: str, chat_id: str, context: dict
    ) -> Any:
        """
        单次执行任务，返回结果字符串或字典。
        【v2.4 核心修复】：优先使用 SkillRouter 获取调用规范，直接调用已有技能。
        """
        # ====================== 【步骤18】第二大脑字符串检索摘要（无向量） ======================
        brain_block = ""
        if self.second_brain is not None and hasattr(self.second_brain, "retrieve_brain_snippets"):
            try:
                snippets = self.second_brain.retrieve_brain_snippets(task, max_files=5)
                if snippets:
                    brain_block = _pp.BRAIN_SNIPPETS_BLOCK.format(snippets=snippets)
                    context["second_brain_snippets"] = snippets
                    logger.info(
                        _plnr_t("plnr.log.brain_snip", n=len(snippets)),
                    )
            except Exception as e:
                logger.warning(_plnr_t("plnr.warn.brain_skip", e=e))
        # =================================================================================

        # ====================== 【核心修复】优先通过 SkillRouter 获取调用规范 ======================
        if self.skill_router:
            try:
                spec = await self.skill_router.get_call_spec(task)
                if spec:
                    # 【v2.4 修复】SkillMetadata 完整兼容处理
                    if hasattr(spec, "skill_name"):
                        skill_name = spec.skill_name
                        args = getattr(spec, "args", {}) or {}
                    elif hasattr(spec, "name"):
                        skill_name = spec.name
                        args = getattr(spec, "args", {}) or {}
                    elif isinstance(spec, (list, tuple)) and len(spec) >= 2:
                        skill_name = spec[0]
                        args = spec[1] if isinstance(spec[1], dict) else {}
                    else:
                        skill_name = str(spec)
                        args = {}

                    # Anthropic 官方“工作流提示技能”：不执行 evolution skill；改为用 prompt_template 指导生成回答
                    if (
                        isinstance(args, dict)
                        and args.get("__skill_source") == "anthropic-official"
                    ):
                        prompt_template = str(args.get("__prompt_template", "") or "").strip()
                        required_params = args.get("__required_params") or []
                        if not prompt_template:
                            logger.warning(_plnr_t("plnr.warn.anthropic_no_tpl", name=skill_name))
                        else:
                            # 提示：required_params 只是“提示词占位符”；这里不强制校验，交给模型按模板生成
                            try:
                                _prior_a = str(
                                    context.get("intent_adaptive_prior_line") or ""
                                ).strip()
                                _intent_meta_block_a = _prior_a + "\n\n" if _prior_a else ""
                                prompt = _pp.ANTHROPIC_SKILL_WRAPPER.format(
                                    skill_name=skill_name,
                                    required_params=required_params,
                                    prompt_template=prompt_template,
                                    intent_meta_block=_intent_meta_block_a,
                                    brain_block=brain_block,
                                    task=task,
                                )
                                text = await self.router.call_llm(
                                    prompt=prompt, brain_type="think", temperature=0.2
                                )
                                return {"status": "success", "data": text}
                            except Exception as e:
                                logger.error(
                                    _plnr_t(
                                        "plnr.err.anthropic_call",
                                        name=skill_name,
                                        e=e,
                                    )
                                )
                                # 失败后继续尝试其他方式

                    skill_key = str(skill_name).upper().strip()
                    skill_func = self.evolution_engine.get_skill(skill_key)
                    if skill_func:
                        try:
                            result = await self.evolution_engine.execute_tool_dispatch(
                                skill_key,
                                args if isinstance(args, dict) else {},
                                trace_id=trace_id,
                                chat_id=chat_id,
                            )
                            logger.info(
                                _plnr_t(
                                    "plnr.log.sr_ok",
                                    tid=trace_id,
                                    sk=skill_key,
                                    args=args,
                                    result=result,
                                )
                            )
                            # 模块五闭环：last30days 写入成功后，调度一次消化任务
                            if (
                                skill_key == "LAST30DAYS_DIGEST"
                                and isinstance(result, dict)
                                and bool(result.get("ok", False))
                                and result.get("note_path")
                            ):
                                try:
                                    await self._schedule_digest_note_task(
                                        note_path=str(result.get("note_path")),
                                        trace_id=str(trace_id),
                                        chat_id=str(chat_id),
                                        source="last30days_digest",
                                    )
                                except Exception as e:
                                    logger.debug(_plnr_t("plnr.debug.sched_skip", e=e))
                            return result  # 【修复】直接返回字典，交由下游 _format_result 处理
                        except Exception as e:
                            logger.error(
                                _plnr_t(
                                    "plnr.err.sr_fail",
                                    tid=trace_id,
                                    sk=skill_key,
                                    e=e,
                                )
                            )
                            # 失败后继续尝试其他方式
            except AttributeError as e:
                # 兼容历史 SkillMetadata（字段 skill_name，而非 name）导致的上游异常；避免每次迭代刷屏。
                msg = str(e)
                if ("SkillMetadata" in msg) and ("name" in msg):
                    if not self._skillrouter_skillmetadata_name_warned:
                        logger.warning(
                            _plnr_t("plnr.warn.sr_meta_once", msg=msg),
                        )
                        self._skillrouter_skillmetadata_name_warned = True
                else:
                    logger.warning(_plnr_t("plnr.warn.sr_attr", e=e))
            except Exception as e:
                logger.warning(_plnr_t("plnr.warn.sr_exc", e=e))
        # =================================================================================

        # ====================== Fallback：原有直接遍历技能的逻辑（增强参数提取） ======================
        all_skills = (
            self.evolution_engine.get_all_skills()
            if hasattr(self.evolution_engine, "get_all_skills")
            else []
        )
        for skill in all_skills:
            skill_name = skill.get("name") or skill.get("skill_name", "")
            if skill_name.lower() in task.lower():
                skill_func = self.evolution_engine.get_skill(skill_name)
                if skill_func:
                    # 提取参数（城市或币种）
                    args = {}
                    # 会议纪要场景白名单（避免误解析为 coin）
                    if (
                        task_matches_pipe_catalog(task, "planner.pipe.meeting_keywords")
                        or "summarize" in task.lower()
                    ):
                        args["transcript"] = task
                    # 天气相关：提取城市名
                    elif task_matches_pipe_catalog(task, "dp.intent.pipe_weather"):
                        city_match = re.search(r"([\u4e00-\u9fff]{2,4})", task)
                        if city_match:
                            args["city"] = city_match.group()
                        else:
                            common_cities = list(
                                catalog_pipe_tokens("shared.pipe.common_cities_cn")
                            )[:10]
                            for city in common_cities:
                                if city in task:
                                    args["city"] = city
                                    break
                    # 价格/加密货币相关：提取币种
                    elif task_matches_pipe_catalog(task, "planner.pipe.crypto_param_hints"):
                        coin_match = re.search(
                            r"(btc|eth|sol|bitcoin|ethereum|solana)", task, re.IGNORECASE
                        )
                        if coin_match:
                            args["coin"] = coin_match.group(1).lower()
                        else:
                            args["coin"] = "bitcoin"
                    try:
                        sk = str(skill_name).upper().strip()
                        result = await self.evolution_engine.execute_tool_dispatch(
                            sk,
                            args if isinstance(args, dict) else {},
                            trace_id=trace_id,
                            chat_id=chat_id,
                        )
                        logger.info(
                            _plnr_t(
                                "plnr.log.direct_ok",
                                tid=trace_id,
                                sk=sk,
                                args=args,
                                result=result,
                            )
                        )
                        return result  # 【修复】直接返回字典，交由下游 _format_result 处理
                    except Exception as e:
                        logger.error(
                            _plnr_t(
                                "plnr.err.direct_fail",
                                tid=trace_id,
                                name=skill_name,
                                e=e,
                            )
                        )
        # =================================================================================

        if task_matches_pipe_catalog(task, "planner.pipe.skill_invoke_hints"):
            all_skills = (
                self.evolution_engine.get_all_skills()
                if hasattr(self.evolution_engine, "get_all_skills")
                else []
            )
            skill_names = [s["name"] for s in all_skills] if all_skills else []
            matched_skill = None
            for s in skill_names:
                if s in task:
                    matched_skill = s
                    break
            if matched_skill:
                skill_func = self.evolution_engine.get_skill(matched_skill)
                if skill_func:
                    # 提取参数（城市或币种）
                    args = {}
                    if task_matches_pipe_catalog(task, "dp.intent.pipe_weather"):
                        city_match = re.search(r"([\u4e00-\u9fff]{2,4})", task)
                        if city_match:
                            args["city"] = city_match.group()
                    elif task_matches_pipe_catalog(task, "planner.pipe.crypto_param_hints"):
                        coin_match = re.search(
                            r"(btc|eth|sol|bitcoin|ethereum|solana)", task, re.IGNORECASE
                        )
                        if coin_match:
                            args["coin"] = coin_match.group(1).lower()
                    ms = str(matched_skill).upper().strip()
                    if args:
                        try:
                            result = await self.evolution_engine.execute_tool_dispatch(
                                ms, args, trace_id=trace_id, chat_id=chat_id
                            )
                            return result  # 【修复】直接返回字典
                        except Exception as e:
                            logger.error(_plnr_t("plnr.err.tool_ms", tid=trace_id, ms=ms, e=e))
                            return t("planner.skill_exec.failed", detail=str(e))
                    else:
                        cities = re.findall(r"([\u4e00-\u9fff]{2,})", task)
                        if len(cities) >= 2:
                            try:
                                result = await skill_func(*cities[:2])
                                return result  # 【修复】直接返回字典
                            except Exception as e:
                                logger.error(
                                    _plnr_t(
                                        "plnr.err.skill_match",
                                        tid=trace_id,
                                        name=matched_skill,
                                        e=e,
                                    )
                                )
                                return t("planner.skill_exec.failed", detail=str(e))
                        else:
                            logger.info(_plnr_t("plnr.log.params_insufficient"))

        if self.skill_composer and self.workflow_engine:
            try:
                all_skills = (
                    self.evolution_engine.get_all_skills()
                    if hasattr(self.evolution_engine, "get_all_skills")
                    else []
                )
                skill_names = [s["name"] for s in all_skills] if all_skills else []
                workflow_state = await self.skill_composer.compose_workflow(task, skill_names)
                if workflow_state and isinstance(workflow_state, WorkflowState):
                    workflow_state.chat_id = str(chat_id)
                    workflow_state.context.update(context)
                    result = await self._execute_composed_workflow_via_bus(workflow_state)
                    if isinstance(result, dict):
                        body = json.dumps(result, ensure_ascii=False, indent=2)
                    else:
                        body = str(result)
                    # Lifecycle evidence: ensure at least one user-visible message contains workflow_id + trace_id.
                    return f"{body}\n\n{t('planner.workflow_engine.evidence_footer', workflow_id=workflow_state.workflow_id, trace_id=trace_id)}"
            except Exception as e:
                error_detail = str(e)
                if hasattr(e, "args") and e.args:
                    error_detail = str(e.args[0])
                friendly_msg = t("planner.skillcomposer.workflow_failed", detail=error_detail)
                logger.warning(_plnr_t("plnr.warn.sc_workflow", detail=error_detail))
                return friendly_msg

        use_multi_agent = getattr(settings, "ADAMI_USE_MULTI_AGENT", True)
        if use_multi_agent and self.multi_agent_orchestrator:
            try:
                future = await self.multi_agent_orchestrator.start_multi_agent_workflow(
                    chat_id=chat_id, task_description=task, initial_context=context
                )
                result = await future
                if isinstance(result, dict):
                    return json.dumps(result, ensure_ascii=False, indent=2)
                return str(result)
            except Exception as e:
                error_detail = str(e)
                if hasattr(e, "args") and e.args:
                    error_detail = str(e.args[0])
                friendly_msg = t("planner.multi_agent.exec_failed", detail=error_detail)
                logger.warning(_plnr_t("plnr.warn.multi_fail", detail=error_detail))
                return friendly_msg

        use_workflow = getattr(settings, "ADAMI_USE_WORKFLOW_ENGINE", True)
        if use_workflow and self.workflow_engine:
            try:
                workflow_id = await self.workflow_engine.start_workflow(
                    chat_id=chat_id, task_description=task
                )
                msg = t("planner.workflow_engine.started", workflow_id=workflow_id)
                return _out(msg, status="success", workflow_id=workflow_id)
            except Exception as e:
                error_detail = str(e)
                friendly_msg = t("planner.workflow_engine.start_failed", detail=error_detail)
                logger.warning(_plnr_t("plnr.warn.wf_start_fail", detail=error_detail))
                return _out(friendly_msg, status="error")

        if self.episodic_memory:
            recall = await self.episodic_memory.recall_errors(task, "plan_and_execute")
            if recall:
                logger.info(_plnr_t("plnr.log.recall", snippet=recall[:100]))

        if mcp_agent_planner_pilot_effective(settings):
            try:
                from adami_kernel.integration.mcp_agent.planner_bridge import try_mcp_agent_planner

                mcp_brain = brain_block or ""
                _prior_m = str(context.get("intent_adaptive_prior_line") or "").strip()
                if _prior_m:
                    mcp_brain = f"{_prior_m}\n\n{mcp_brain}".strip()
                mcp_text = await try_mcp_agent_planner(task, mcp_brain)
                if mcp_text is not None:
                    return mcp_text
            except Exception as e:
                logger.warning(_plnr_t("plnr.warn.mcp_pilot", e=e))

        plan = await self._generate_plan(
            task,
            brain_block,
            intent_meta_line=str(context.get("intent_adaptive_prior_line") or ""),
        )
        if not plan or "steps" not in plan:
            return t("planner.plan.failed_no_steps")

        steps = plan["steps"][:3]
        results = []
        for step in steps:
            action = step.get("action", "").upper()
            args = step.get("args", {})
            await asyncio.sleep(1.2)
            try:
                if action == "WEB_SEARCH":
                    res = await self.evolution_engine.toolbox.web.search(args.get("query", task))
                elif action == "CREATE_NEW_SKILL":
                    tdd_result = await self.tdd_evolution.create_skill_with_tdd(
                        task_description=args.get("description", task)
                    )
                    if tdd_result.get("status") == "solidified":
                        res = t(
                            "planner.step.skill_tdd_solidified",
                            skill_name=tdd_result.get("skill_name", ""),
                        )
                    else:
                        res = t(
                            "planner.step.skill_tdd_failed",
                            reason=str(tdd_result.get("reason") or ""),
                        )
                elif action == "SUMMARIZE":
                    res = await self._builtin_summarize(args.get("text", _pp.NO_TEXT_FALLBACK))
                else:
                    res = await self.evolution_engine.execute_with_retry(
                        action, args, trace_id=trace_id, chat_id=chat_id
                    )
                results.append(str(res))
            except Exception as e:
                error_detail = str(e)
                results.append(t("planner.step.step_failed", detail=error_detail))
                break
        return "\n".join(results)

    async def _generate_plan(
        self, task: str, brain_preamble: str = "", *, intent_meta_line: str = ""
    ) -> Dict:
        tools_section = self.evolution_engine.get_registered_tools_for_llm() or ""
        MAX_TOOLS_LENGTH = 2000
        if len(tools_section) > MAX_TOOLS_LENGTH:
            tools_section = tools_section[:MAX_TOOLS_LENGTH] + _pp.TOOLS_SECTION_TRUNCATED_SUFFIX

        preamble = brain_preamble or ""
        intent_meta_block = ""
        if intent_meta_line:
            intent_meta_block = intent_meta_line.strip() + "\n\n"
        prompt = _pp.GENERATE_PLAN_PROMPT.format(
            preamble=preamble,
            intent_meta_block=intent_meta_block,
            tools_section=tools_section,
            task=task,
        )

        raw = await self.router.call_llm(prompt=prompt, brain_type="think", temperature=0.1)
        return self._extract_json(raw)

    async def _builtin_summarize(self, text: str) -> str:
        prompt = _pp.BUILTIN_SUMMARIZE_PROMPT.format(text=text[:3000])
        return await self.router.call_llm(prompt=prompt, brain_type="think", temperature=0.2)

    def _extract_json(self, raw: str) -> Dict:
        result = extract_json_from_llm_output(raw)
        if result is not None:
            return result
        logger.warning(_plnr_t("plnr.warn.json_extract"))
        return {
            "steps": [
                {"action": "WEB_SEARCH", "args": {"query": "2026 AI news"}},
                {"action": "SUMMARIZE", "args": {"count": 3}},
            ]
        }

    async def pause_plan(self, trace_id: str) -> str:
        if hasattr(self, "multi_agent_orchestrator") and self.multi_agent_orchestrator:
            await self.multi_agent_orchestrator.pause_workflow(trace_id)
            return t("planner.multi_agent.pause_ok", trace_id=trace_id)
        return t("planner.multi_agent.plan_not_found")

    async def resume_plan(self, trace_id: str) -> str:
        if hasattr(self, "multi_agent_orchestrator") and self.multi_agent_orchestrator:
            await self.multi_agent_orchestrator.resume_workflow(trace_id)
            return t("planner.multi_agent.resume_ok", trace_id=trace_id)
        return t("planner.multi_agent.plan_not_found")


# --- END OF FILE src/adami_kernel/orchestrator/planner.py ---
# 文件路径：src/adami_kernel/orchestrator/planner.py
# 版本：v2.4（SkillMetadata 完整兼容版）
