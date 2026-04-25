# --- START OF FILE meta_cortex.py ---

import json
import logging
import time  # 用于全量测试防抖
from typing import Any, Dict

from rich.console import Console

from adami_kernel.config import settings

# ====================== 【Bug 12 核心修复】使用公共 JSON 解析器 ======================
from adami_kernel.cortex.tools.json_parser import extract_json_from_llm_output

# =================================================================================
# ====================== 【本次核心修复】集成 GraphMemory 图谱引擎 ======================
from adami_kernel.hippocampus.graph_memory import GraphMemory
from adami_kernel.i18n import t

# =================================================================================
# ====================== 【2.0 阶段3 新增】ReflexionLoop 集成 ======================
from adami_kernel.orchestrator.reflexion_loop import ReflexionLoop

# =================================================================================
# ====================== 【本次集成】SelfTestEngine ======================
from adami_kernel.self_test.self_test_engine import SelfTestEngine

# =================================================================================

logger = logging.getLogger("AdamI-MetaCortex")
console = Console()


def _mcx_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class MetaCortex:
    """
    元认知与长期规划层 (MetaCortex)
    超越单次反馈，定期执行【记忆洗髓】（整合矛盾经验），评估进化进度，并生成基因组长期规划。
    已完整适配 LayeredMemory（UnifiedMemory）—— retrieve_recent / clear_and_rewrite_domain 均已实现
    【Bug 12 核心修复】：所有 JSON 解析已统一调用 extract_json_from_llm_output（DRY）
    【Bug 12 扩展修复】：所有 retrieve_recent 调用均增加 chat_id 隔离支持
    【本次核心修复】：集成 GraphMemory，实现实体-关系图谱化记忆与子图推理
    【阶段3 增强】：evaluate_and_plan 集成 ReflexionLoop，实现失败自动自愈闭环
    【本次核心集成】：evaluate_and_plan 前置 SelfTestEngine 自我验证，确保进化前先自测
    【本次最终修复】：SelfTest 防抖按 chat_id 完全隔离，支持多租户独立计时
    """

    def __init__(self, router, memory, evolution_engine, curiosity_queue):
        self.router = router
        self.memory = memory  # ← LayeredMemory（UnifiedMemory）
        self.evolution_engine = evolution_engine
        self.curiosity = curiosity_queue

        # ====================== 【本次新增】注入 GraphMemory 图谱引擎 ======================
        self.graph_memory = GraphMemory()
        # =================================================================================

        # ====================== 【阶段3 新增】ReflexionLoop 实例 ======================
        self.reflexion_loop: ReflexionLoop = None
        # =================================================================================

        # ====================== 【本次修复】SelfTestEngine 实例 + 按 chat_id 隔离的防抖计时器 ======================
        self.self_test_engine: SelfTestEngine = None
        self.last_full_test_time: Dict[str, float] = {}  # key: chat_id or "system"
        # =================================================================================

        # ====================== 【新增】评估防抖计时器 ======================
        self._last_eval_time = 0.0
        # =================================================================================

    def set_reflexion_loop(self, reflexion_loop: ReflexionLoop):
        """【阶段3 新增】注入 ReflexionLoop"""
        self.reflexion_loop = reflexion_loop
        logger.info(_mcx_t("metc.log.refl_inject"))

    # ====================== 【Step 7 新增】注入 SelfTestEngine ======================
    def set_self_test_engine(self, self_test_engine: SelfTestEngine):
        """注入 SelfTestEngine，实现进化前自我验证"""
        self.self_test_engine = self_test_engine
        logger.info(_mcx_t("metc.log.selftest_inject"))

    # =================================================================================

    # ====================== 【Bug 12 核心修复】增加 chat_id 参数 ======================
    async def evaluate_and_plan(
        self,
        current_persona: str,
        endocrine_status: str,
        chat_id: str = None,
        failure_context: Dict[str, Any] = None,
        run_self_test: bool = False,
    ):
        # ====================== 【新增】全局防抖：30秒内只执行一次 ======================
        now = time.time()
        if now - self._last_eval_time < 30:
            logger.debug(_mcx_t("metc.debug.eval_skip", sec=f"{now - self._last_eval_time:.1f}"))
            return {"assessment": _mcx_t("mcx.assessment.rate_limited"), "genome_plan": []}
        self._last_eval_time = now
        # =================================================================================

        # ====================== 【本次修复】按 chat_id 隔离的 SelfTest 防抖 ======================
        if self.self_test_engine and run_self_test:
            now = time.time()
            chat_key = chat_id or "system"
            last_time = self.last_full_test_time.get(chat_key, 0)

            if last_time == 0 or (now - last_time) > 3600:
                logger.info(_mcx_t("metc.log.selftest_start", cid=chat_key))
                test_report = await self.self_test_engine.run_full_test_suite(chat_id=chat_id)
                self.last_full_test_time[chat_key] = now

                if test_report.get("status") != "success" or test_report.get("pass_rate", 0) < 0.95:
                    logger.warning(_mcx_t("metc.warn.selftest_fail"))
                    if self.reflexion_loop:
                        await self.reflexion_loop.trigger_reflexion(
                            workflow_id=f"meta_evo_{int(time.time())}",
                            chat_id=chat_id or "system",
                            failure_context={
                                "error": f"SelfTest pass_rate={test_report.get('pass_rate')}",
                                "task_description": _mcx_t("mcx.selftest.task_label"),
                            },
                        )
                    return
                logger.info(
                    _mcx_t(
                        "metc.log.selftest_pass",
                        rate=f"{test_report.get('pass_rate'):.2%}",
                    )
                )
            else:
                logger.info(_mcx_t("metc.log.selftest_skip_hour", cid=chat_key))
        # =================================================================================

        # ====================== 【阶段3 增强】失败检测 → 自动触发 Reflexion ======================
        if failure_context and self.reflexion_loop:
            logger.info(_mcx_t("metc.log.task_fail_refl"))
            await self.reflexion_loop.trigger_reflexion(
                workflow_id=failure_context.get("workflow_id", "unknown"),
                chat_id=chat_id or "system",
                failure_context=failure_context,
            )
        # =================================================================================

        logger.info(_mcx_t("metc.log.deep_scan"))

        # 1. 【记忆洗髓 (Memory Consolidation & Pruning)】
        current_rules = await self.memory.retrieve_recent(
            "semantic_rules", limit=20, chat_id=chat_id
        )

        if len(current_rules) > 5:
            logger.info(_mcx_t("metc.log.rules_merge", n=len(current_rules)))
            rules_text = "\n".join([f"- {r.get('insight', '')}" for r in current_rules])

            prune_prompt = _mcx_t("mcx.prompt.prune", rules_text=rules_text)

            prune_response = await self.router.call_llm(
                prune_prompt, brain_type="think", temperature=0.2
            )
            if prune_response:
                data = extract_json_from_llm_output(prune_response)
                if data:
                    axioms = data.get("axioms", [])
                    if axioms:
                        new_payloads = [{"insight": ax} for ax in axioms]
                        await self.memory.clear_and_rewrite_domain(
                            "semantic_rules", new_payloads, chat_id=chat_id
                        )

                        logger.info(_mcx_t("metc.log.axiom_title"))
                        for ax in axioms:
                            logger.info(_mcx_t("metc.log.axiom_line", line=ax))

                        if self.graph_memory.enabled:
                            entities = [
                                {"id": f"axiom_{i}", "type": "Axiom", "name": ax}
                                for i, ax in enumerate(axioms)
                            ]
                            relationships = [
                                {
                                    "source": "Self",
                                    "target": f"axiom_{i}",
                                    "relation": "HOLDS_AXIOM",
                                }
                                for i, ax in enumerate(axioms)
                            ]
                            await self.graph_memory.merge_knowledge(entities, relationships)
                            logger.info(_mcx_t("metc.log.axiom_graph", n=len(axioms)))

        # 2. 【长效生命评估与规划】
        history = await self.memory.retrieve_recent("code_ops", limit=15, chat_id=chat_id)
        history_str = (
            json.dumps(history, ensure_ascii=False)[:2500]
            if history
            else _mcx_t("mcx.history.empty")
        )

        graph_insight = ""
        if self.graph_memory.enabled:
            subgraph = await self.graph_memory.query_subgraph("Self", hops=2, limit=8)
            if subgraph:
                graph_insight = _mcx_t("mcx.graph.header") + "\n".join(
                    [
                        f"{item.get('source')} --[{item.get('relation')}]--> {item.get('target')}"
                        for item in subgraph
                    ]
                )

        # ====================== 【新增】获取最近进化反馈 ======================
        feedbacks = await self.memory.retrieve_recent(
            "evolution_feedback", limit=10, chat_id=chat_id
        )
        feedback_summary = ""
        if feedbacks:
            feedback_summary = _mcx_t("mcx.feedback.header")
            for f in feedbacks:
                if not isinstance(f, dict):
                    continue
                status = (
                    _mcx_t("mcx.feedback.status_ok")
                    if f.get("install_success")
                    else _mcx_t("mcx.feedback.status_fail")
                )
                score = f.get("score", 0)
                pass_rate = (
                    f.get("test_pass_rate", 0) * 100
                    if f.get("test_pass_rate") is not None
                    else "N/A"
                )
                line = _mcx_t(
                    "mcx.feedback.line",
                    skill=f.get("skill_name"),
                    status=status,
                    score=score,
                    pass_rate=pass_rate,
                )
                if f.get("solidified"):
                    line += _mcx_t("mcx.feedback.solidified_suffix")
                feedback_summary += line + "\n"
        # =================================================================================

        plan_prompt = _mcx_t(
            "mcx.prompt.plan",
            current_persona=current_persona,
            endocrine_status=endocrine_status,
            history_str=history_str,
            graph_insight=graph_insight,
            feedback_summary=feedback_summary,
        )

        plan_response = await self.router.call_llm(plan_prompt, brain_type="think", temperature=0.6)
        if not plan_response:
            return

        try:
            data = extract_json_from_llm_output(plan_response)
            if data:
                assessment = data.get("assessment", "")
                plan = data.get("genome_plan", [])

                logger.info(_mcx_t("metc.log.assess", text=assessment))

                if plan and self.curiosity:
                    logger.info(_mcx_t("metc.log.gene_plan", plan=plan))
                    for target in plan:
                        self.curiosity.add_curiosity(
                            _mcx_t("mcx.curiosity.longgoal_prefix") + str(target)
                        )
                # 返回计划
                return {"assessment": assessment, "genome_plan": plan}
        except Exception as e:
            logger.error(_mcx_t("metc.err.plan_parse", e=e))
        # =================================================================================
        # 如果以上都没有返回，返回默认计划
        return {
            "assessment": _mcx_t("mcx.default.assessment_fail"),
            "genome_plan": ["web_search", "create_new_skill"],
        }


# --- END OF FILE meta_cortex.py ---
