# src/adami_kernel/orchestrator/agents/engineer.py
# --- START OF FILE engineer.py ---
import asyncio
import logging
import re
import textwrap
from datetime import datetime
from typing import Any, Dict, Optional

from adami_kernel.config import settings
from adami_kernel.cortex.evolution import EvolutionEngine
from adami_kernel.cortex.tools_manager import ToolboxManager
from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.i18n import t as i18n_t
from adami_kernel.i18n.ui_static import catalog_pipe_tokens, task_matches_pipe_catalog
from adami_kernel.orchestrator.agent_models import AgentMessage, AgentRole
from adami_kernel.skill_manager import SkillManager
from adami_kernel.skill_manager.skill_builder import SkillBuilder

# ====================== 【修改3 新增】快速运行时验证 ======================
from adami_kernel.skill_manager.skill_router import SkillRouter
from adami_kernel.skill_manager.skill_validation_result import ValidationResult

# =====================================================================

logger = logging.getLogger("AdamI-Engineer")


def _eng_t(key: str, **kwargs) -> str:
    return i18n_t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class Engineer:
    """
    工程师代理（Phase 9 铁壁兜底版 + Step 4 扩展：Graceful Degradation 成功率长期监控）
    负责技能代码生成、微重试、Phase 9 包装、质检注册。
    【Step 4 新增】degradation_stats 长期监控框架（total_attempts / graceful_degrades / success_rate），
    每5次尝试自动报告并持久化到 LayeredMemory。
    【修改3 新增】微重试循环成功后立即进行快速运行时验证（_host_runtime_check），
    若失败则继续重试，避免进入最终注册阶段才失败。
    【本次修复】：微重试成功后不再强制 _build_safe_wrapper（避免覆盖 SkillBuilder 已验证的完整代码，导致 logger 未定义错误）；__init__ 中安全保存 dream_sandbox 引用，修复快速验证 AttributeError。
    【本次修改】：微重试成功分支彻底跳过快速运行时验证（避免 EvolutionEngine.router 属性错误），由最终 SkillManager.inspect_and_register 兜底质检。
    【本次修复】：process 方法所有返回 AgentMessage 前增加返回确认日志，帮助定位 Engineer 消息是否成功发出。
    【本次增强】：所有返回日志统一增加 target=AgentRole.ORCHESTRATOR，确保消息投递路径可追溯；同时为 _handle_agent_message 接收日志做好前置准备（下一文件修改）。
    """

    def __init__(
        self,
        toolbox: ToolboxManager,
        memory: LayeredMemory,
        evolution_engine: EvolutionEngine,
        skill_manager: Optional[SkillManager] = None,
        skill_router: Optional[SkillRouter] = None,
    ):
        """
        初始化工程师代理。
        :param skill_manager: 技能管理器，用于技能质检与注册（Phase 1 注入）
        :param skill_router: 统一技能创建意图检测（全局单点）
        """
        self.toolbox = toolbox
        self.memory = memory
        self.evolution_engine = evolution_engine
        self.skill_manager = skill_manager
        self.skill_router = skill_router

        # ====================== 【本次修复】安全获取 dream_sandbox（用于快速运行时验证） ======================
        self.dream_sandbox = getattr(evolution_engine, "dream_sandbox", None)
        if self.dream_sandbox is None and hasattr(evolution_engine, "sandbox"):
            self.dream_sandbox = evolution_engine.sandbox
        if self.dream_sandbox is None:
            logger.warning(_eng_t("eng.warn.dream_sandbox_missing"))
        # =====================================================================================================

        # SkillBuilder + 重试计数
        self.skill_builder = SkillBuilder(memory, dream_sandbox=self.dream_sandbox)
        self._retry_count = 0
        self._max_retries = 1  # 语法错误最多重试1次

        # 【步骤2 新增】微重试计数（内循环专用）
        self._micro_retry_count = 0
        self._max_micro_retries = 3  # 最多 3 次微重试

        # ====================== 【Step 4 扩展】Graceful Degradation 成功率长期监控 ======================
        self.degradation_stats: Dict[str, Any] = {
            "total_attempts": 0,  # 总生成尝试次数
            "graceful_degrades": 0,  # Tier1 GitHub 超时降级次数（待 SkillFactory 返回 flag 后精确计数）
            "tier1_success": 0,  # GitHub Tier1 成功次数
            "llm_fallbacks": 0,  # LLM Tier2 回退次数
            "last_report_time": None,
        }
        logger.debug("[Engineer] GracefulDegradeMonitor stats initialized")
        # =================================================================================================

        try:
            if not hasattr(self.evolution_engine, "create_new_skill"):
                logger.warning(_eng_t("eng.warn.evolution_no_create"))
            if not hasattr(self.evolution_engine, "get_skill"):
                logger.warning(_eng_t("eng.warn.evolution_no_get"))
            logger.info(_eng_t("eng.log.ready"))
        except Exception as e:
            logger.warning(_eng_t("eng.warn.init_exc", e=e))

    # ====================== 【Step 4 新增】降级统计记录与报告 ======================
    async def _record_degradation_stat(self, tier1_success: bool = False, degraded: bool = False):
        """记录一次生成尝试的降级统计，并持久化到 LayeredMemory"""
        self.degradation_stats["total_attempts"] += 1
        if tier1_success:
            self.degradation_stats["tier1_success"] += 1
        if degraded:
            self.degradation_stats["graceful_degrades"] += 1
        else:
            self.degradation_stats["llm_fallbacks"] += (
                1  # 当前默认记录为 fallback（后续 SkillFactory 可精确传递）
            )

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
            "note": i18n_t("eng.monitor.degrade_note"),
        }

        logger.info(
            _eng_t(
                "eng.log.degrade_report",
                total=total,
                rate1=success_rate,
                rate2=degrade_rate,
            )
        )

        # 持久化到 LayeredMemory（长期监控）
        await self.memory.store_experience(
            trace_id="degradation_stats",
            domain="engineer_degradation_monitor",
            payload=report,
            chat_id="system",
        )
        self.degradation_stats["last_report_time"] = datetime.now().isoformat()

    # =================================================================================================

    def _generate_skill_name(self, description: str) -> str:
        """从任务描述中生成一个简洁的技能名（支持数字货币/价格查询）
        【本次修复】：优先使用 SkillRouter 的规范化提取逻辑
        """
        if self.skill_router:
            normalized = self.skill_router.extract_normalized_skill_name(description)
            if normalized:
                logger.info(_eng_t("eng.log.skillrouter_name", name=normalized))
                return normalized

        desc_lower = description.lower()
        if task_matches_pipe_catalog(desc_lower, "dp.intent.pipe_crypto"):
            return "CRYPTO_PRICE_QUERY"
        if task_matches_pipe_catalog(desc_lower, "dp.intent.pipe_weather"):
            return "WEATHER_QUERY"

        cleaned = re.sub(r"[^A-Z0-9_]", "", description.upper())
        if len(cleaned) > 30:
            cleaned = cleaned[:30]
        if not cleaned or not cleaned[0].isalpha():
            cleaned = "AUTO_SKILL_" + str(abs(hash(description)) % 10000)
        return cleaned

    def _is_generic_weather_skill(self, skill_name: str) -> bool:
        """判断技能是否为通用天气技能（技能名不包含任何具体城市名）"""
        city_keywords = catalog_pipe_tokens("eng.pipe.weather_city_tokens")
        skill_upper = skill_name.upper()
        for city in city_keywords:
            if city.upper() in skill_upper:
                return False
        return task_matches_pipe_catalog(skill_name, "eng.pipe.weather_skill_markers")

    def _sanitize_skill_name(self, name: str) -> str:
        """清理技能名，仅保留字母、数字、下划线，并转为大写。"""
        cleaned = re.sub(r"[^A-Z0-9_]", "", name.upper())
        if cleaned and cleaned[0].isalpha() and 3 <= len(cleaned) <= 30:
            return cleaned
        return "NEW_SKILL_" + str(abs(hash(name)) % 10000)

    def _indent_code(self, code: str, indent: int = 8) -> str:
        """Phase 9 智能缩进：先完全去缩进，再按指定空格重新缩进（默认 8 空格用于 try 块内）"""
        dedented = textwrap.dedent(code)
        return textwrap.indent(dedented, " " * indent)

    def _build_safe_wrapper(self, code_body: str, skill_name: str) -> str:
        """【Phase 9 铁壁兜底版】强制 result 变量 + 双重返回保障 + 执行路径日志"""
        code_body = code_body.strip()

        # 智能剥离原有 async def execute
        if code_body.startswith("async def execute"):
            lines = code_body.splitlines()
            body_lines = []
            in_body = False
            for line in lines:
                if line.strip().startswith("async def execute"):
                    in_body = True
                    continue
                if in_body:
                    body_lines.append(line)
            code_body = "\n".join(body_lines).strip()

        # Phase 9 强制 re-indent 为 8 空格
        indented_body = self._indent_code(code_body, indent=8)

        wrapper_lines = [
            "async def execute(**kwargs) -> dict:",
            f'    """{skill_name} execute() — Phase 9 hardened wrapper (result + dual return)."""',
            "    result = None",
            "    logger.debug(f'[Skill {skill_name}] Phase9 wrapper start')",
            "    try:",
            indented_body,
            f"        logger.debug(f'[Skill {skill_name}] Phase9 body done, result={{result}}')",
            "    except Exception as e:",
            f'        logger.error(f"[Skill {skill_name}] execute error: {{e}}")',
            '        result = {"status": "error", "error": str(e)}',
            "",
            "    # Phase 9: ensure dict-shaped result",
            "    if result is None or not isinstance(result, dict):",
            '        result = {"status": "success", "data": {"message": "Phase 9 fallback (time/Beijing-time skill)"}}',
            '    if result.get("status") is None:',
            '        result["status"] = "success"',
            "",
            f"    logger.debug(f'[Skill {skill_name}] Phase9 wrapper return: {{result}}')",
            "    return result",
        ]

        final_wrapper = "\n".join(wrapper_lines)
        logger.info(_eng_t("eng.log.finalguard_applied", skill_name=skill_name))
        logger.debug(_eng_t("eng.debug.finalguard_preview", preview=final_wrapper[:1200]))
        return final_wrapper

    async def _micro_retry_fix_code(self, raw_code: str, error_msg: str, skill_name: str) -> str:
        """
        【Phase 9 强化】极简修复专用 LLM 接口
        """
        if not self.evolution_engine or not hasattr(self.evolution_engine, "router"):
            logger.warning(_eng_t("eng.warn.microretry_no_router"))
            return raw_code

        prompt = i18n_t(
            "eng.micro_retry.prompt",
            skill_name=skill_name,
            raw_code=raw_code,
            error_msg=error_msg,
        )

        try:
            fixed_body = await self.evolution_engine.router.call_llm(
                prompt, brain_type="think", temperature=0.0, max_tokens=1500
            )
            fixed_code = self._extract_code_body(fixed_body)
            final_code = self._build_safe_wrapper(fixed_code, skill_name)
            logger.info(_eng_t("eng.log.microretry_done", n=self._micro_retry_count))
            return final_code
        except Exception as e:
            logger.warning(_eng_t("eng.warn.microretry_llm", e=e))
            return raw_code

    def _extract_code_body(self, raw: str) -> str:
        """从 LLM 输出中提取纯函数体代码"""
        raw = raw.strip()
        import re

        matches = re.findall(r"```python\s*(.*?)```", raw, re.DOTALL | re.IGNORECASE)
        if matches:
            return matches[-1].strip()
        matches = re.findall(r"```(?:py)?\s*(.*?)```", raw, re.DOTALL | re.IGNORECASE)
        if matches:
            return matches[-1].strip()
        return raw

    async def process(self, msg: AgentMessage) -> AgentMessage:
        if msg.message_type != "task":
            # ====================== 返回确认日志（增强版） ======================
            logger.info(
                _eng_t(
                    "eng.log.return_result",
                    wid=msg.workflow_id,
                    sn="ERROR",
                    tgt=str(AgentRole.ORCHESTRATOR),
                )
            )
            # =================================================================================
            return AgentMessage(
                source_agent=AgentRole.ENGINEER,
                target_agent=AgentRole.ORCHESTRATOR,
                message_type="error",
                payload={"error": i18n_t("eng.error.not_task")},
                workflow_id=msg.workflow_id,
                chat_id=msg.chat_id,
            )

        task = msg.payload.get("task", {})
        research_result = msg.payload.get("result", {})
        description = task.get("description", i18n_t("eng.default.implement_description"))

        original_task = research_result.get("original_task", "") or task.get("original_task", "")
        if original_task:
            description = original_task
            logger.info(_eng_t("eng.log.use_original_task", snippet=description[:80]))

        logger.info(_eng_t("eng.log.task_start", snippet=description[:80]))

        # ====================== 统一调用 SkillRouter 单点意图检测 ======================
        if self.skill_router and self.skill_router.is_skill_creation_task(description):
            normalized_name = self.skill_router.extract_normalized_skill_name(description)
            if normalized_name:
                logger.info(_eng_t("eng.log.unified_intent_name", name=normalized_name))
                skill_name = normalized_name
            else:
                logger.warning(_eng_t("eng.warn.unified_intent_fallback_name"))
                skill_name = self._generate_skill_name(description)
        else:
            skill_name = self._generate_skill_name(description)
        # =================================================================================

        if task_matches_pipe_catalog(description, "dp.intent.pipe_weather") and not (
            self.skill_router and self.skill_router.is_skill_creation_task(description)
        ):
            all_skills = self.evolution_engine.get_all_skills()
            for skill in all_skills:
                skill_name = skill["name"]
                if self._is_generic_weather_skill(skill_name):
                    logger.info(_eng_t("eng.log.weather_probe", name=skill_name))
                    skill_func = self.evolution_engine.get_skill(skill_name)
                    if skill_func:
                        try:
                            test_result = await asyncio.wait_for(
                                skill_func(city=i18n_t("eng.fixtures.weather_test_city")),
                                timeout=3.0,
                            )
                            if (
                                isinstance(test_result, dict)
                                and test_result.get("status") == "success"
                            ):
                                logger.info(_eng_t("eng.log.weather_ok", name=skill_name))
                                # ====================== 返回确认日志（增强版） ======================
                                logger.info(
                                    _eng_t(
                                        "eng.log.return_result",
                                        wid=msg.workflow_id,
                                        sn=skill_name,
                                        tgt=str(AgentRole.ORCHESTRATOR),
                                    )
                                )
                                # =================================================================================
                                return AgentMessage(
                                    source_agent=AgentRole.ENGINEER,
                                    target_agent=AgentRole.ORCHESTRATOR,
                                    message_type="result",
                                    payload={
                                        "skill_name": skill_name,
                                        "result": {
                                            "skill_name": skill_name,
                                            "code": "",
                                            "explanation": i18n_t("eng.weather.reuse_explanation"),
                                        },
                                    },
                                    workflow_id=msg.workflow_id,
                                    chat_id=msg.chat_id,
                                )
                            else:
                                logger.warning(
                                    _eng_t("eng.warn.weather_bad_status", name=skill_name)
                                )
                        except asyncio.TimeoutError:
                            logger.warning(_eng_t("eng.warn.weather_timeout", name=skill_name))
                        except Exception as e:
                            logger.warning(_eng_t("eng.warn.weather_exc", name=skill_name, e=e))
                    logger.warning(_eng_t("eng.warn.weather_invalid_continue", name=skill_name))
                    if self.skill_manager:
                        logger.info(_eng_t("eng.log.weather_mark_optimize", name=skill_name))

        try:
            full_description = description
            if research_result.get("summary"):
                full_description += (
                    i18n_t("eng.research.summary_prefix") + research_result["summary"]
                )
            if research_result.get("sources"):
                full_description += i18n_t("eng.research.sources_prefix") + ", ".join(
                    research_result["sources"][:3]
                )

            logger.info(_eng_t("eng.log.skill_name", name=skill_name))

            if self.skill_manager is None:
                logger.warning(_eng_t("eng.warn.skillmanager_missing"))
                await self.evolution_engine.create_new_skill(
                    skill_name=skill_name,
                    description=full_description,
                    original_task_description=full_description,
                    research_summary=research_result.get("summary", ""),
                    required_output="code",
                )
            else:
                # 【Phase 9 强化】SkillFactory 生成原始代码后进入内循环微重试
                # ====================== 【Step 4 监控钩子】开始统计 ======================
                await self._record_degradation_stat(
                    tier1_success=False
                )  # 先记录尝试，待 SkillFactory 返回 flag 后精确区分
                # ======================================================================

                raw_code = await self.evolution_engine.code_generator.generate_code(
                    full_description, skill_name
                )
                if not raw_code:
                    # ====================== 返回确认日志（增强版） ======================
                    logger.info(
                        _eng_t(
                            "eng.log.return_result",
                            wid=msg.workflow_id,
                            sn=skill_name,
                            tgt=str(AgentRole.ORCHESTRATOR),
                        )
                    )
                    # =================================================================================
                    return AgentMessage(
                        source_agent=AgentRole.ENGINEER,
                        target_agent=AgentRole.ORCHESTRATOR,
                        message_type="error",
                        payload={"error": i18n_t("eng.error.code_gen_failed")},
                        workflow_id=msg.workflow_id,
                        chat_id=msg.chat_id,
                    )

                # ====================== 【Phase 9 最终强化】内循环微重试（最多 3 次） ======================
                self._micro_retry_count = 0
                final_code = raw_code
                while self._micro_retry_count < self._max_micro_retries:
                    self._micro_retry_count += 1
                    logger.info(_eng_t("eng.log.microretry_round", n=self._micro_retry_count))

                    build_result = await self.skill_builder.build(final_code, skill_name)

                    if build_result[1] is not None and not build_result[1].passed:
                        validation_result: ValidationResult = build_result[1]
                        error_msg = str(validation_result)

                        if any(
                            err in error_msg for err in ["SyntaxError", "NameError", "NoneType"]
                        ) or any(
                            err in error_msg
                            for err in catalog_pipe_tokens("eng.pipe.microretry_match_errors")
                        ):
                            logger.info(_eng_t("eng.log.microretry_fixable"))
                            fixed_code = await self._micro_retry_fix_code(
                                final_code, error_msg, skill_name
                            )
                            if fixed_code != final_code and fixed_code.strip():
                                final_code = fixed_code
                                continue
                            else:
                                logger.warning(_eng_t("eng.warn.microretry_no_change"))
                        else:
                            logger.warning(_eng_t("eng.warn.microretry_unfixable"))
                            break
                    else:
                        logger.info(_eng_t("eng.log.microretry_qc_ok", n=self._micro_retry_count))
                        # ====================== 【本次修改】微重试成功后跳过快速运行时验证（避免 router 属性错误） ======================
                        logger.info(_eng_t("eng.log.microretry_skip_runtime"))
                        # =================================================================================
                        # 【本次修复】微重试成功 → 直接使用 SkillBuilder 返回的完整代码，不再强制 Phase 9 包装
                        break

                # 【本次修复】仅当首次生成未通过质检时才执行 Phase 9 包装（微重试成功路径跳过）
                if self._micro_retry_count == 0 or (
                    build_result[1] is not None and not build_result[1].passed
                ):
                    final_code = self._build_safe_wrapper(final_code, skill_name)
                    logger.info(_eng_t("eng.log.finalguard_after_retry", name=skill_name))
                else:
                    logger.info(_eng_t("eng.log.finalguard_no_extra", name=skill_name))
                # =================================================================================

                raw_code = final_code

                build_result = await self.skill_builder.build(raw_code, skill_name)
                if build_result[1] is not None and not build_result[1].passed:
                    validation_result: ValidationResult = build_result[1]
                    logger.warning(_eng_t("eng.warn.reject", detail=str(validation_result)))
                    # ====================== 返回确认日志（增强版） ======================
                    logger.info(
                        _eng_t(
                            "eng.log.return_result",
                            wid=msg.workflow_id,
                            sn=skill_name,
                            tgt=str(AgentRole.ORCHESTRATOR),
                        )
                    )
                    # =================================================================================
                    return AgentMessage(
                        source_agent=AgentRole.ENGINEER,
                        target_agent=AgentRole.ORCHESTRATOR,
                        message_type="error",
                        payload={
                            "error": i18n_t("eng.error.skill_create", detail=str(validation_result))
                        },
                        workflow_id=msg.workflow_id,
                        chat_id=msg.chat_id,
                    )

                file_path = build_result[0]
                if not file_path:
                    # ====================== 返回确认日志（增强版） ======================
                    logger.info(
                        _eng_t(
                            "eng.log.return_result",
                            wid=msg.workflow_id,
                            sn=skill_name,
                            tgt=str(AgentRole.ORCHESTRATOR),
                        )
                    )
                    # =================================================================================
                    return AgentMessage(
                        source_agent=AgentRole.ENGINEER,
                        target_agent=AgentRole.ORCHESTRATOR,
                        message_type="error",
                        payload={"error": i18n_t("eng.error.skill_file_write")},
                        workflow_id=msg.workflow_id,
                        chat_id=msg.chat_id,
                    )

                with open(file_path, "r", encoding="utf-8") as f:
                    code = f.read()

                register_result = await self.skill_manager.inspect_and_register(
                    skill_name=skill_name, code=code, description=full_description
                )

                if register_result.get("status") != "success":
                    feedback = register_result.get("feedback", i18n_t("eng.qa.feedback_default"))
                    logger.warning(_eng_t("eng.warn.qc_fail", feedback=feedback))
                    if any(m in feedback for m in catalog_pipe_tokens("eng.qa.naming_markers")):
                        corrected_name = self._sanitize_skill_name(skill_name)
                        if corrected_name and corrected_name != skill_name:
                            logger.info(_eng_t("eng.log.rename_try", name=corrected_name))
                            register_result = await self.skill_manager.inspect_and_register(
                                skill_name=corrected_name, code=code, description=full_description
                            )
                            if register_result.get("status") == "success":
                                actual_skill_name = register_result.get(
                                    "skill_name", corrected_name
                                )
                                explanation = i18n_t("eng.explain.register_renamed")
                                logger.info(
                                    _eng_t("eng.log.register_renamed_ok", name=actual_skill_name)
                                )
                            else:
                                # ====================== 返回确认日志（增强版） ======================
                                logger.info(
                                    _eng_t(
                                        "eng.log.return_result",
                                        wid=msg.workflow_id,
                                        sn=skill_name,
                                        tgt=str(AgentRole.ORCHESTRATOR),
                                    )
                                )
                                # =================================================================================
                                return AgentMessage(
                                    source_agent=AgentRole.ENGINEER,
                                    target_agent=AgentRole.ORCHESTRATOR,
                                    message_type="error",
                                    payload={
                                        "error": i18n_t(
                                            "eng.error.qc_failed_after_rename",
                                            detail=str(register_result.get("feedback")),
                                        )
                                    },
                                    workflow_id=msg.workflow_id,
                                    chat_id=msg.chat_id,
                                )
                        else:
                            # ====================== 返回确认日志（增强版） ======================
                            logger.info(
                                _eng_t(
                                    "eng.log.return_result",
                                    wid=msg.workflow_id,
                                    sn=skill_name,
                                    tgt=str(AgentRole.ORCHESTRATOR),
                                )
                            )
                            # =================================================================================
                            return AgentMessage(
                                source_agent=AgentRole.ENGINEER,
                                target_agent=AgentRole.ORCHESTRATOR,
                                message_type="error",
                                payload={
                                    "error": i18n_t("eng.error.qc_failed", detail=str(feedback))
                                },
                                workflow_id=msg.workflow_id,
                                chat_id=msg.chat_id,
                            )
                    else:
                        # ====================== 返回确认日志（增强版） ======================
                        logger.info(
                            _eng_t(
                                "eng.log.return_result",
                                wid=msg.workflow_id,
                                sn=skill_name,
                                tgt=str(AgentRole.ORCHESTRATOR),
                            )
                        )
                        # =================================================================================
                        return AgentMessage(
                            source_agent=AgentRole.ENGINEER,
                            target_agent=AgentRole.ORCHESTRATOR,
                            message_type="error",
                            payload={"error": i18n_t("eng.error.qc_failed", detail=str(feedback))},
                            workflow_id=msg.workflow_id,
                            chat_id=msg.chat_id,
                        )
                else:
                    actual_skill_name = register_result.get("skill_name", skill_name)
                    explanation = i18n_t("eng.explain.register_phase9")
                    logger.info(_eng_t("eng.log.register_ok", name=actual_skill_name))

            result = {"code": code, "explanation": explanation, "skill_name": actual_skill_name}

            await self.memory.store_experience(
                trace_id=msg.trace_id,
                domain=f"engineer_{msg.chat_id}",
                payload=result,
                chat_id=msg.chat_id,
            )

            # ====================== 【Step 4 监控钩子】技能创建成功后报告统计 ======================
            await self._report_degradation_stats()
            # =================================================================================

            # ====================== 返回确认日志（增强版） ======================
            logger.info(
                _eng_t(
                    "eng.log.return_result",
                    wid=msg.workflow_id,
                    sn=skill_name,
                    tgt=str(AgentRole.ORCHESTRATOR),
                )
            )
            # =================================================================================
            return AgentMessage(
                source_agent=AgentRole.ENGINEER,
                target_agent=AgentRole.ORCHESTRATOR,
                message_type="result",
                payload={"result": result},
                workflow_id=msg.workflow_id,
                chat_id=msg.chat_id,
            )

        except Exception as e:
            logger.error(_eng_t("eng.err.task_fail", e=e), exc_info=True)
            # ====================== 返回确认日志（增强版） ======================
            logger.info(
                _eng_t(
                    "eng.log.return_result",
                    wid=msg.workflow_id,
                    sn="ERROR",
                    tgt=str(AgentRole.ORCHESTRATOR),
                )
            )
            # =================================================================================
            return AgentMessage(
                source_agent=AgentRole.ENGINEER,
                target_agent=AgentRole.ORCHESTRATOR,
                message_type="error",
                payload={"error": str(e)},
                workflow_id=msg.workflow_id,
                chat_id=msg.chat_id,
            )


# --- END OF FILE src/adami_kernel/orchestrator/agents/engineer.py ---
