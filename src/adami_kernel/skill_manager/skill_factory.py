# src/adami_kernel/skill_manager/skill_factory.py
# --- START OF FILE skill_factory.py ---
"""
AdamI Skill Manager - SkillFactory（第三阶段增强版 + 第四阶段 TDD 后置验证 + 主动进化钩子 + Step 4 强力执行回退降级）

【v2.14 核心修复】：彻底解除 _post_validate_tdd 的同步阻塞，采用 asyncio.create_task 后台执行，大幅缩短生成链路耗时。
【v2.13 核心修复】：GitHubBackend 默认后端增加 1.5秒硬超时保护 + GracefulDegrade 立即降级
对外统一提供 generate_code 接口，根据配置动态选择后端（Template / Anthropic / GitHub Tier1 / LLM / Tier3）。
集成 GitHubHunter 高星库优先 + SkillWasher 洗髓 + Tier 2/3 回退逻辑 + Anthropic Skills 导入器。
"""

import asyncio
import json
import logging
import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

from adami_kernel.config import settings
from adami_kernel.hippocampus.episodic_memory import EpisodicMemory
from adami_kernel.hippocampus.second_brain import SecondBrainManager
from adami_kernel.i18n import t as i18n_t
from adami_kernel.i18n.boot_msg import boot_t
from adami_kernel.market.github_hunter import GitHubHunter
from adami_kernel.skill_manager.anthropic_skill_importer import AnthropicSkillImporter
from adami_kernel.skill_manager.skill_code_generator import SkillCodeGenerator
from adami_kernel.skill_manager.skill_tdd_generator import SkillTDDGenerator
from adami_kernel.skill_manager.skill_template_repository import SkillTemplateRepository
from adami_kernel.skill_manager.skill_washer import SkillWasher

if TYPE_CHECKING:
    from adami_kernel.cortex.dream_sandbox import DreamSandbox

logger = logging.getLogger("AdamI-SkillFactory")


def _sfac_t(key: str, **kwargs) -> str:
    return i18n_t(key, locale=settings.effective_ui_default_locale(), **kwargs)


def _sfac_name_map() -> dict[str, str]:
    return json.loads(_sfac_t("sfac.name.map_json"))


def _sfac_stopwords() -> frozenset[str]:
    return frozenset(json.loads(_sfac_t("sfac.name.stopwords_json")))


def _sfac_unknown_skill() -> str:
    return i18n_t("sfac.name.unknown_lit", locale="zh-Hans")


class SkillCodeBackend(ABC):
    """抽象代码生成后端（可插拔）"""

    @abstractmethod
    async def generate(self, description: str, skill_name: str) -> str:
        pass


class TemplateBackend(SkillCodeBackend):
    """模板后端（优先级最高）"""

    def __init__(self):
        self.repo = SkillTemplateRepository()

    async def generate(self, description: str, skill_name: str) -> str:
        template = self.repo.get_template(description, skill_name)
        if template:
            logger.info(_sfac_t("sfac.log.template_use", name=skill_name))
            return template
        return ""


class AnthropicBackend(SkillCodeBackend):
    """Anthropic Skills 官方仓库后端"""

    def __init__(self):
        self.importer = AnthropicSkillImporter()

    async def generate(self, description: str, skill_name: str) -> str:
        logger.info(_sfac_t("sfac.log.anthropic_try", name=skill_name))

        skill_meta = self.importer.import_single_skill(skill_name.lower())
        if skill_meta and getattr(skill_meta, "prompt_template", None):
            logger.info(
                _sfac_t(
                    "sfac.log.anthropic_ok",
                    name=getattr(skill_meta, "skill_name", skill_name),
                )
            )
            return skill_meta.prompt_template

        all_skills = self.importer.scan_and_import()
        for meta in all_skills:
            meta_name = getattr(meta, "skill_name", "") or getattr(meta, "name", "")
            meta_desc = getattr(meta, "description", "") or getattr(meta, "summary", "")
            if (
                skill_name.lower() in str(meta_name).lower()
                or skill_name.lower() in str(meta_desc).lower()
            ):
                logger.info(_sfac_t("sfac.log.anthropic_fuzzy", name=meta_name))
                return getattr(meta, "prompt_template", "")

        logger.warning(_sfac_t("sfac.warn.anthropic_miss"))
        return ""


class LLMBackend(SkillCodeBackend):
    """LLM 后端（Tier 2）"""

    def __init__(self, router):
        self.generator = SkillCodeGenerator(router=router)

    async def generate(self, description: str, skill_name: str) -> str:
        logger.info(_sfac_t("sfac.log.llm_tier2", name=skill_name))
        return await self.generator.generate_code(description, skill_name)


class GitHubBackend(SkillCodeBackend):
    """GitHub 高星库后端（Tier 1 首选）"""

    def __init__(self, router, dream_sandbox: Optional["DreamSandbox"] = None):
        self.hunter = GitHubHunter(router)
        self.washer = SkillWasher(dream_sandbox=dream_sandbox)

    async def generate(self, description: str, skill_name: str) -> str:
        logger.info(_sfac_t("sfac.log.github_tier1_start", name=skill_name))
        github_code = await self.hunter.search_and_extract(
            query=description, min_stars=settings.ADAMI_GITHUB_MIN_STARS, language="python", limit=3
        )
        if not github_code:
            logger.warning(_sfac_t("sfac.warn.github_tier1_miss"))
            return ""

        washed_code = await self.washer.wash(github_code, skill_name)
        logger.info(_sfac_t("sfac.log.github_tier1_done", name=skill_name))
        return washed_code


class SkillFactory:
    """
    技能代码工厂（多后端 + Tier 分层获取 + TDD 后置异步验证）
    【v2.14 核心修复】：TDD 验证改为后台异步任务，彻底解除 Engineer 主流程阻塞
    """

    def __init__(self, router, dream_sandbox: Optional["DreamSandbox"] = None):
        self.router = router
        self._dream_sandbox = dream_sandbox
        self.episodic = EpisodicMemory()
        self.second_brain = SecondBrainManager()
        self._backend = None

        self.tdd_generator = SkillTDDGenerator(router)
        self.anthropic_importer = AnthropicSkillImporter()

        self._init_backend()

    def _init_backend(self):
        backend_type = getattr(settings, "ADAMI_SKILL_BACKEND", "template").lower()

        if backend_type == "template":
            self._backend = TemplateBackend()
            logger.info(boot_t("boot.log.skill_factory_backend", backend="TemplateBackend"))
        elif backend_type == "anthropic":
            self._backend = AnthropicBackend()
            logger.info(boot_t("boot.log.skill_factory_backend", backend="AnthropicBackend"))
        elif backend_type == "llm":
            self._backend = LLMBackend(self.router)
            logger.info(boot_t("boot.log.skill_factory_backend", backend="LLMBackend"))
        elif backend_type == "github":
            self._backend = GitHubBackend(self.router, dream_sandbox=self._dream_sandbox)
            logger.info(boot_t("boot.log.skill_factory_backend", backend="GitHubBackend Tier1"))
        else:
            logger.warning(
                boot_t("boot.log.skill_factory_backend_unknown", backend_type=backend_type)
            )
            self._backend = TemplateBackend()

    def _normalize_skill_name(self, skill_name: str, description: str) -> str:
        """根据描述生成干净可读技能名称"""
        desc = description.strip()
        desc = re.sub(r"参考来源[:：].*?web.*?", "", desc, flags=re.IGNORECASE)
        desc = re.sub(r"web[,，\s]+", "", desc, flags=re.IGNORECASE)
        desc = re.sub(r"来源[:：].*?", "", desc, flags=re.IGNORECASE)
        desc = re.sub(r"\s+", " ", desc).strip()

        if (
            skill_name
            and skill_name not in (_sfac_unknown_skill(), "TEMP_SKILL", "UNKNOWN_SKILL", "")
            and not skill_name.startswith("AUTO_SKILL_")
        ):
            normalized = re.sub(r"[^A-Z0-9_]", "_", skill_name.upper())
            return normalized

        for cn, en in _sfac_name_map().items():
            desc = desc.replace(cn, en)

        words = re.findall(r"[\u4e00-\u9fa5a-zA-Z0-9_]+", desc)
        _sw = _sfac_stopwords()
        meaningful_words = [w.upper() for w in words if len(w) >= 2 and w not in _sw]

        if meaningful_words:
            inferred = "_".join(meaningful_words[:4])
            logger.info(_sfac_t("sfac.log.naming_infer", name=inferred))
            return inferred

        fallback = "AUTO_SKILL_" + str(abs(hash(desc)) % 100000)
        logger.warning(_sfac_t("sfac.warn.naming_fallback", name=fallback))
        return fallback

    async def generate_code(self, description: str, skill_name: str) -> str:
        skill_name = self._normalize_skill_name(skill_name, description)
        logger.info(_sfac_t("sfac.log.gen_start", name=skill_name))

        # ====================== 【核心修复】对默认后端的硬超时保护 ======================
        if isinstance(self._backend, GitHubBackend):
            try:
                code = await asyncio.wait_for(
                    self._backend.generate(description, skill_name), timeout=1.5
                )
            except asyncio.TimeoutError:
                logger.info(_sfac_t("sfac.log.github_timeout"))
                code = ""
            except Exception as e:
                logger.warning(_sfac_t("sfac.warn.github_exc", e=e))
                code = ""
        else:
            code = await self._backend.generate(description, skill_name)
        # ================================================================================

        if code.strip():
            # 【v2.14 修复】采用后台任务执行，不阻塞后续流程
            asyncio.create_task(self._post_validate_tdd(skill_name, code))
            return code

        logger.info(_sfac_t("sfac.log.tier_anthropic"))

        if not isinstance(self._backend, AnthropicBackend):
            anthropic_backend = AnthropicBackend()
            code = await anthropic_backend.generate(description, skill_name)
            if code.strip():
                asyncio.create_task(self._post_validate_tdd(skill_name, code))
                return code

        logger.info(_sfac_t("sfac.log.tier_github"))

        if not isinstance(self._backend, GitHubBackend):
            github_backend = GitHubBackend(self.router, dream_sandbox=self._dream_sandbox)
            try:
                code = await asyncio.wait_for(
                    github_backend.generate(description, skill_name), timeout=1.0
                )
            except asyncio.TimeoutError:
                logger.info(_sfac_t("sfac.log.github_tier1_timeout"))
                code = ""
            except Exception as e:
                logger.warning(_sfac_t("sfac.warn.github_tier1_exc", e=e))
                code = ""

            if code.strip():
                asyncio.create_task(self._post_validate_tdd(skill_name, code))
                return code

        logger.info(_sfac_t("sfac.log.tier2_llm"))

        llm_backend = LLMBackend(self.router)
        code = await llm_backend.generate(description, skill_name)
        if code.strip():
            asyncio.create_task(self._post_validate_tdd(skill_name, code))
            return code

        logger.info(_sfac_t("sfac.log.tier3"))

        history_code = await self._get_from_history(description, skill_name)
        if history_code:
            logger.info(_sfac_t("sfac.log.tier3_from_history", name=skill_name))
            asyncio.create_task(self._post_validate_tdd(skill_name, history_code))
            return history_code

        logger.error(_sfac_t("sfac.err.all_tiers_fail"))
        return ""

    async def _post_validate_tdd(self, skill_name: str, code: str):
        """异步 TDD 后置验证（后台任务，不阻塞主流程）"""
        logger.info(_sfac_t("sfac.log.tdd_start", name=skill_name))
        try:
            await self.tdd_generator.generate_test_cases(skill_name, code)
            logger.info(_sfac_t("sfac.log.tdd_done", name=skill_name))
        except Exception as e:
            logger.warning(_sfac_t("sfac.warn.tdd_exc", name=skill_name, e=e))

    async def trigger_active_evolution(self, skill_name: Optional[str] = None):
        if skill_name:
            logger.info(_sfac_t("sfac.log.evo_trigger", name=skill_name))
            if hasattr(self, "skill_optimizer") and self.skill_optimizer:
                await self.skill_optimizer.optimize(skill_name)
            else:
                logger.warning(_sfac_t("sfac.warn.evo_no_optimizer"))
        else:
            logger.info(_sfac_t("sfac.log.evo_scan"))

    async def _get_from_history(self, description: str, skill_name: str) -> Optional[str]:
        try:
            history = await self.episodic.recall(
                query=description, domain="skill_success", n_results=3
            )
            if history:
                return history[0].get("code", "")

            brain_code = await self.second_brain.search_similar_skill(description)
            if brain_code:
                return brain_code
        except Exception as e:
            logger.warning(_sfac_t("sfac.warn.tier3_hist", e=e))
        return None
