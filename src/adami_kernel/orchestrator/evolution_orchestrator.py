# src/adami_kernel/orchestrator/evolution_orchestrator.py
import asyncio
import logging
import re
import time
from datetime import datetime
from typing import Any, Dict

from adami_kernel.config import settings
from adami_kernel.cortex.evolution import EvolutionEngine
from adami_kernel.cortex.meta_cortex import MetaCortex
from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.cortex.endocrine import status_or_normal
from adami_kernel.market.github_hunter import GitHubHunter
from adami_kernel.market.skill_market import SkillMarket
from adami_kernel.self_test.self_test_engine import SelfTestEngine

logger = logging.getLogger("AdamI-EvolutionOrchestrator")


class EvolutionOrchestrator:
    def __init__(
        self,
        meta_cortex: MetaCortex,
        skill_market: SkillMarket,
        github_hunter: GitHubHunter,
        self_test_engine: SelfTestEngine,
        evolution_engine: EvolutionEngine,
        memory: LayeredMemory,
        router=None,
        endocrine=None,
    ):  # 新增 router 参数
        self.meta_cortex = meta_cortex
        self.skill_market = skill_market
        self.github_hunter = github_hunter
        self.self_test_engine = self_test_engine
        self.evolution_engine = evolution_engine
        self.memory = memory
        self.router = router  # 保存 router 供评估使用
        self.endocrine = endocrine
        self._running = False

    async def start(self):
        if not getattr(settings, "ADAMI_AUTO_EVOLUTION_ENABLED", True):
            logger.info(boot_t("boot.log.evolution_auto_disabled"))
            return

        interval = getattr(settings, "ADAMI_AUTO_EVOLUTION_INTERVAL_HOURS", 6) * 3600
        self._running = True
        while self._running:
            try:
                await self._evolution_cycle()
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(boot_t("boot.log.evolution_cycle_error", detail=str(e)), exc_info=True)
                await asyncio.sleep(300)

    # ====================== 仓库质量过滤器 ======================
    def _is_quality_repo(self, repo: Dict[str, Any]) -> bool:
        """检查仓库是否符合质量要求 - 工业级可配置过滤器（v2.1）"""
        # 1. 必须为 Python 仓库（处理 None 和未知语言）
        language = repo.get("language")
        if language is None:
            logger.debug(
                boot_t("boot.log.evolution_debug_skip_no_language", name=repo.get("full_name"))
            )
            return False
        language_lower = language.lower()
        if language_lower not in ("python", "jupyter notebook"):
            logger.debug(
                boot_t(
                    "boot.log.evolution_debug_skip_non_python",
                    name=repo.get("full_name"),
                    language=language,
                )
            )
            return False

        # 2. 名称不能过短，不能以 '.' 开头
        name = repo.get("name", "")
        if len(name) < 3 or name.startswith("."):
            logger.debug(boot_t("boot.log.evolution_debug_skip_bad_name", name=name))
            return False

        # 3. 描述不能为空或过短（阈值略微提升）
        description = repo.get("description", "")
        if not description or len(description) < 15:
            logger.debug(
                boot_t("boot.log.evolution_debug_skip_short_desc", name=repo.get("full_name"))
            )
            return False

        # 4. 可配置精准黑名单 + 白名单（通过 config.py 注入）
        blacklist_keywords = set(
            kw.lower()
            for kw in getattr(
                settings,
                "ADAMI_EVOLUTION_BLACKLIST_KEYWORDS",
                ["dictatorship", "china", "spam", "malware", "fake", "scam", "virus"],
            )
        )
        whitelist_keywords = set(
            kw.lower()
            for kw in getattr(
                settings,
                "ADAMI_EVOLUTION_WHITELIST_KEYWORDS",
                ["example", "tutorial", "demo", "sample", "boilerplate", "starter"],
            )
        )

        name_lower = name.lower()
        desc_lower = description.lower()

        # 使用 set + 正则精准匹配（\b 边界，避免子串误杀）
        def has_keyword(text: str, keywords: set) -> bool:
            for kw in keywords:
                if re.search(r"\b" + re.escape(kw) + r"\b", text):
                    return True
            return False

        # 白名单优先通过（即使 fork 较低也直接保留）
        is_whitelisted = has_keyword(name_lower, whitelist_keywords) or has_keyword(
            desc_lower, whitelist_keywords
        )

        # 黑名单检查（白名单可覆盖）
        if has_keyword(name_lower, blacklist_keywords) or has_keyword(
            desc_lower, blacklist_keywords
        ):
            if not is_whitelisted:
                logger.debug(boot_t("boot.log.evolution_debug_skip_blacklist", name=name))
                return False

        # 5. topics 二次验证
        topics = repo.get("topics", []) or []
        topics_lower = [t.lower() for t in topics]
        if topics:
            if any(kw in topics_lower for kw in blacklist_keywords):
                if not any(wl in topics_lower for wl in whitelist_keywords):
                    logger.debug(
                        boot_t("boot.log.evolution_debug_skip_topics_blacklist", name=name)
                    )
                    return False

        # 6. star/fork ratio 二次验证（白名单豁免低 fork 检查）
        stars = repo.get("stars", 0)
        forks = repo.get("forks", 0)
        if stars < 1000:
            logger.debug(
                boot_t(
                    "boot.log.evolution_debug_skip_low_stars",
                    name=repo.get("full_name"),
                    score=repo.get("score", 0),
                )
            )
            return False
        if stars > 0:
            fork_ratio = forks / stars
            if fork_ratio > 3.0:  # 过高 forks 可能为推广型低质仓库
                logger.debug(
                    boot_t(
                        "boot.log.evolution_debug_skip_fork_ratio_high",
                        name=name,
                        ratio=f"{fork_ratio:.2f}",
                    )
                )
                return False
            if fork_ratio < 0.05 and stars < 5000 and not is_whitelisted:  # 白名单豁免
                logger.debug(
                    boot_t(
                        "boot.log.evolution_debug_skip_fork_ratio_low",
                        name=name,
                        ratio=f"{fork_ratio:.2f}",
                    )
                )
                return False

        # 7. 最终分数检查（保持原有逻辑）
        score = repo.get("score", 0)
        if score < 1000:
            logger.debug(
                boot_t(
                    "boot.log.evolution_debug_skip_low_final_score",
                    name=repo.get("full_name"),
                    score=score,
                )
            )
            return False

        return True

    # =================================================================

    async def _evolution_cycle(self):
        logger.info(boot_t("boot.log.evolution_cycle_start"))
        plan = await self.meta_cortex.evaluate_and_plan(
            current_persona=boot_t("cjk_gate.meta_cortex_proactive_persona"),
            endocrine_status=status_or_normal(self.endocrine),
        )
        if plan is None:
            logger.warning(boot_t("boot.log.evolution_meta_empty_plan"))
            return
        targets = plan.get("genome_plan", [])
        if not targets:
            logger.info(boot_t("boot.log.evolution_no_targets"))
            return

        concrete_map = {
            "web_search": "web scraping python",
            "create_new_skill": "python automation script",
            "crypto": "cryptocurrency price python",
            "api_integration": "rest api client python",
            "data_analysis": "pandas data analysis example",
        }
        concrete_targets = []
        for t in targets:
            if t in concrete_map:
                concrete_targets.append(concrete_map[t])
            else:
                concrete_targets.append(t)
        targets = concrete_targets
        logger.info(boot_t("boot.log.evolution_concrete_keywords", targets=str(targets)))

        # 获取重试次数配置
        max_retries = getattr(settings, "ADAMI_AUTO_EVOLUTION_MAX_RETRIES", 3)

        for target in targets[:3]:
            repos = await self.github_hunter.search_repos(query=target, min_stars=2000, limit=5)
            for repo in repos:
                repo["score"] = repo["stars"] * 0.7 + repo["forks"] * 0.3
            repos.sort(key=lambda x: x["score"], reverse=True)

            for repo in repos:
                # 跳过不符合质量要求的仓库
                if not self._is_quality_repo(repo):
                    continue

                all_skills = await self.skill_market.list_all_skills()
                installed_names = {s["name"].upper() for s in all_skills}
                skill_name_candidate = repo["name"].upper()
                if skill_name_candidate in installed_names:
                    logger.info(
                        boot_t(
                            "boot.log.evolution_skill_already_installed", skill=skill_name_candidate
                        )
                    )
                    continue

                # ====================== 增加重试逻辑 ======================
                install_success = False
                last_error = None
                result = None
                for attempt in range(max_retries):
                    logger.info(
                        boot_t(
                            "boot.log.evolution_install_attempt",
                            repo=repo["full_name"],
                            attempt=attempt + 1,
                            max_retries=max_retries,
                        )
                    )
                    result = await self.skill_market.install_skill(
                        skill_name=skill_name_candidate, source="github", repo_url=repo["html_url"]
                    )
                    if result.get("status") == "success":
                        install_success = True
                        break
                    else:
                        last_error = result.get("error")
                        logger.warning(
                            boot_t(
                                "boot.log.evolution_install_attempt_fail",
                                skill=skill_name_candidate,
                                attempt=attempt + 1,
                                max_retries=max_retries,
                                error=last_error,
                            )
                        )
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2**attempt)  # 指数退避

                if not install_success:
                    logger.warning(
                        boot_t(
                            "boot.log.evolution_install_give_up",
                            skill=skill_name_candidate,
                            max_retries=max_retries,
                        )
                    )
                    # 记录安装失败反馈
                    feedback = {
                        "skill_name": skill_name_candidate,
                        "repo": repo["full_name"],
                        "stars": repo["stars"],
                        "forks": repo["forks"],
                        "score": repo["score"],
                        "install_success": False,
                        "install_error": last_error,
                        "timestamp": datetime.now().isoformat(),
                    }
                    await self.memory.store_experience(
                        trace_id=f"evolution_feedback_{skill_name_candidate}_{int(time.time())}",
                        domain="evolution_feedback",
                        payload=feedback,
                        chat_id="system",
                    )
                    continue

                logger.info(boot_t("boot.log.evolution_install_ok", skill=skill_name_candidate))
                # ========================================================

                # ====================== 新增评估：技能是否符合目标 ======================
                if self.router:
                    # 获取技能代码（优先从安装结果中提取）
                    code = result.get("data", {}).get("code", "")
                    if not code:
                        # 尝试重新拉取代码
                        try:
                            code = await self.github_hunter.fetch_code(repo["html_url"])
                        except Exception as e:
                            logger.warning(
                                boot_t(
                                    "boot.log.evolution_fetch_code_fail",
                                    skill=skill_name_candidate,
                                    detail=str(e),
                                )
                            )

                    if code:
                        from adami_kernel.orchestrator.task_evaluator import TaskEvaluator

                        evaluator = TaskEvaluator(self.router)
                        eval_res = await evaluator.evaluate(target, code, {})
                        if not eval_res.get("completed", False):
                            logger.warning(
                                boot_t(
                                    "boot.log.evolution_eval_incomplete",
                                    skill=skill_name_candidate,
                                    remaining=eval_res.get("remaining", ""),
                                )
                            )
                            # 跳过该仓库，不进行后续测试和固化
                            continue
                    else:
                        logger.warning(
                            boot_t(
                                "boot.log.evolution_no_code_skip_eval", skill=skill_name_candidate
                            )
                        )
                else:
                    logger.warning(boot_t("boot.log.evolution_router_missing"))
                # ============================================================

                # 技能试用
                trial_result = None
                try:
                    trial_result = await self.evolution_engine.execute_in_sandbox(
                        skill_name_candidate, {"test_mode": True}
                    )
                    if (
                        not isinstance(trial_result, dict)
                        or trial_result.get("status") != "success"
                    ):
                        logger.warning(
                            boot_t("boot.log.evolution_trial_fail_keep", skill=skill_name_candidate)
                        )
                    else:
                        logger.info(
                            boot_t("boot.log.evolution_trial_ok", skill=skill_name_candidate)
                        )
                except Exception as e:
                    logger.warning(
                        boot_t(
                            "boot.log.evolution_trial_exception_keep",
                            skill=skill_name_candidate,
                            detail=str(e),
                        )
                    )

                # 运行自测
                test_report = await self.self_test_engine.run_critical_tests(
                    workflow_id=f"evolution_{skill_name_candidate}"
                )
                solidified = False
                if (
                    test_report.get("status") == "success"
                    and test_report.get("pass_rate", 0) >= 0.8
                ):
                    # 固化为本能
                    code = result.get("data", {}).get("code", "")
                    solidified = await self.evolution_engine.melt_and_solidify(
                        skill_name_candidate, code
                    )
                    if solidified:
                        logger.info(
                            boot_t("boot.log.evolution_solidify_ok", skill=skill_name_candidate)
                        )
                    else:
                        logger.warning(
                            boot_t("boot.log.evolution_solidify_fail", skill=skill_name_candidate)
                        )
                else:
                    logger.warning(
                        boot_t(
                            "boot.log.evolution_tests_fail_keep_dynamic", skill=skill_name_candidate
                        )
                    )

                # 记录反馈
                feedback = {
                    "skill_name": skill_name_candidate,
                    "repo": repo["full_name"],
                    "stars": repo["stars"],
                    "forks": repo["forks"],
                    "score": repo["score"],
                    "install_success": True,
                    "trial_success": trial_result.get("status") == "success"
                    if trial_result
                    else None,
                    "test_pass_rate": test_report.get("pass_rate"),
                    "solidified": solidified,
                    "timestamp": datetime.now().isoformat(),
                }
                await self.memory.store_experience(
                    trace_id=f"evolution_feedback_{skill_name_candidate}_{int(time.time())}",
                    domain="evolution_feedback",
                    payload=feedback,
                    chat_id="system",
                )

        await self.memory.store_experience(
            trace_id=f"evolution_{int(asyncio.get_event_loop().time())}",
            domain="evolution_log",
            payload={"targets": targets, "timestamp": asyncio.get_event_loop().time()},
            chat_id="system",
        )

    async def trigger_manual(self):
        logger.info(boot_t("boot.log.evolution_manual_trigger"))
        await self._evolution_cycle()

    async def stop(self):
        self._running = False


# src/adami_kernel/orchestrator/evolution_orchestrator.py
