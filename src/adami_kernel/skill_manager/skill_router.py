# src/adami_kernel/skill_manager/skill_router.py
# --- START OF FILE skill_router.py ---
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from adami_kernel.config import settings
from adami_kernel.cortex.evolution import EvolutionEngine
from adami_kernel.cortex.router import LLMRouter
from adami_kernel.cortex.tools.json_parser import extract_json_from_llm_output
from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.i18n import t as i18n_t
from adami_kernel.i18n.ui_static import (
    catalog_pipe_tokens,
    catalog_synonym_map,
    task_matches_pipe_catalog,
)
from adami_kernel.skill_manager.anthropic_skill_importer import AnthropicSkillImporter

logger = logging.getLogger("AdamI-SkillRouter")


def _skrt_t(key: str, **kwargs) -> str:
    return i18n_t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class SkillRouter:
    """
    技能路由器（Phase 2 + 增强后备 + Anthropic Skills 完整支持 v2.2）
    职责：根据用户任务，智能匹配已有技能并提取调用参数。
    若匹配成功，返回 (skill_name, args)；否则返回 None，触发技能创建流程。
    【Phase 2 强化】新增严格污染过滤，成为真正的“防污染网关”。
    【本次修复】：is_skill_creation_task 成为全系统单点意图检测方法（planner.py 已调用）
    【本次重构】：_decide_and_extract 增加明确的参数翻译规则（如以太坊转eth），解决传参偏差。
    【本次修复】：新增 extract_normalized_skill_name 解决技能名称提取 Bug
    【步骤4 新增】：完整支持 Anthropic Skills 官方技能路由（缓存 + 最高优先级 + prompt_template 注入）
    """

    def __init__(
        self,
        memory: LayeredMemory,
        llm_router: LLMRouter,
        evolution_engine: Optional[EvolutionEngine] = None,
    ):
        self.memory = memory
        self.llm_router = llm_router
        self.evolution_engine = evolution_engine
        self.vector_store = None

        self.anthropic_importer = AnthropicSkillImporter()
        self.anthropic_skills_cache: List[Dict] = []

        loc = settings.effective_ui_default_locale()
        self._synonym_map = catalog_synonym_map()
        self._creation_keywords = catalog_pipe_tokens("sr.pipe.creation_keywords")
        self._invocation_keywords = catalog_pipe_tokens("sr.pipe.invocation_keywords")
        self._bad_patterns = catalog_pipe_tokens("sr.pipe.bad_patterns")
        self._stopwords = frozenset(catalog_pipe_tokens("sr.pipe.token_stopwords"))
        self._creation_regex = re.compile(
            i18n_t("sr.regex.creation_skill", locale=loc),
            re.IGNORECASE,
        )
        self.pollution_pattern = re.compile(r"[\u4e00-\u9fff]{5,}")

        logger.debug(_skrt_t("skrt.debug.init"))

    def extract_normalized_skill_name(self, user_task: str) -> Optional[str]:
        """
        【本次核心修复】严格提取并规范化技能名称
        规则：
        1. 支持“创建一个技能：TEST_SKILL_003”、“创建技能 TEST_SKILL_003”等格式
        2. 只保留大写字母、数字、下划线
        3. 必须以字母开头
        4. 长度 3-30 个字符
        """
        task = user_task.strip()
        match = self._creation_regex.search(task)
        if match and match.group(1):
            raw_name = match.group(1).strip()
        else:
            fallback = re.findall(r"\b([A-Z][A-Z0-9_]{2,})\b", task)
            raw_name = fallback[0] if fallback else None

        if not raw_name:
            t = task.lower()
            inferred = None
            if task_matches_pipe_catalog(t, "dp.intent.pipe_crypto"):
                inferred = "CRYPTO_PRICE_QUERY"
            elif task_matches_pipe_catalog(t, "dp.intent.pipe_weather"):
                inferred = "WEATHER_QUERY"
            elif task_matches_pipe_catalog(t, "dp.intent.pipe_tsunami"):
                inferred = "TSUNAMI_ALERT_QUERY"

            if inferred:
                logger.info(_skrt_t("skrt.log.inferred", name=inferred))
                return inferred
            return None

        normalized = re.sub(r"[^A-Z0-9_]", "", raw_name.upper())
        if len(normalized) < 3 or len(normalized) > 30 or not normalized[0].isalpha():
            logger.warning(_skrt_t("skrt.warn.norm_fail", raw=raw_name, norm=normalized))
            return None

        logger.info(_skrt_t("skrt.log.norm_ok", raw=raw_name, norm=normalized))
        return normalized

    def is_skill_creation_task(self, user_task: str) -> bool:
        """
        技能创建意图检测（全系统单点维护方法）
        planner.py 已迁移调用此处，避免重复逻辑。
        【本次增强】同时进行技能名规范化
        """
        task_lower = user_task.lower().strip()

        if self._creation_regex.search(task_lower):
            return True
        if any(kw in task_lower for kw in self._creation_keywords):
            return True

        skill_names = []
        if self.evolution_engine:
            all_skills = self.evolution_engine.get_all_skills()
            skill_names = [s["name"].lower() for s in all_skills]

        starts_with_invocation = any(
            task_lower.startswith(kw) or task_lower.startswith(kw + " ")
            for kw in self._invocation_keywords
        )

        if starts_with_invocation:
            for skill_name in skill_names:
                if skill_name in task_lower:
                    logger.debug(_skrt_t("skrt.debug.invoke_intent"))
                    return False

        return False

    def _is_polluted_skill(self, skill_name: str) -> bool:
        """严格污染检测（Anthropic 官方技能自动豁免）"""
        if not skill_name:
            return False
        if skill_name.upper().startswith("ANTHROPIC_") or "anthropic" in skill_name.lower():
            return False
        if len(skill_name) > 30:
            return True
        if self.pollution_pattern.search(skill_name):
            return True
        if any(bad in skill_name for bad in self._bad_patterns):
            return True
        return False

    async def get_call_spec(self, user_task: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        主入口：根据用户任务获取技能调用规范。
        【Phase 2 强化】污染过滤 + 创建意图早停 + 技能名规范化
        【步骤4 增强】支持 Anthropic Skills 官方技能
        """
        logger.info(_skrt_t("skrt.log.task_recv", task=user_task))

        if self.is_skill_creation_task(user_task):
            normalized_name = self.extract_normalized_skill_name(user_task)
            if normalized_name:
                logger.info(_skrt_t("skrt.log.create_named", name=normalized_name))
            else:
                logger.warning(_skrt_t("skrt.warn.create_noname"))
            return None

        candidates = await self._get_candidates(user_task)
        if not candidates:
            logger.info(_skrt_t("skrt.log.no_candidates"))
            return None

        logger.info(_skrt_t("skrt.log.candidates_n", n=len(candidates)))

        decision = await self._decide_and_extract(user_task, candidates)
        if not decision or not decision.get("matched"):
            logger.info(_skrt_t("skrt.log.llm_no_match"))
            return None

        skill_name = decision["skill_name"]
        args = decision.get("args", {})
        logger.info(_skrt_t("skrt.log.match_ok", name=skill_name, args=args))
        return (skill_name, args)

    async def _get_candidates(self, user_task: str, top_k: int = 5) -> List[Dict]:
        """获取候选技能（Anthropic Skills 最高优先级 + 缓存）"""
        if self.is_skill_creation_task(user_task):
            return []

        candidates = []

        if not self.anthropic_skills_cache:
            anthropic_skills = self.anthropic_importer.scan_and_import()
            self.anthropic_skills_cache = [
                {
                    "skill_name": getattr(meta, "skill_name", None) or getattr(meta, "name", None),
                    "description": meta.description,
                    "source": "anthropic-official",
                    "prompt_template": meta.prompt_template,
                    "required_params": getattr(meta, "required_params", None) or [],
                }
                for meta in anthropic_skills
            ]
            logger.info(_skrt_t("skrt.log.anth_cache_n", n=len(self.anthropic_skills_cache)))

        candidates.extend(self.anthropic_skills_cache)

        if self.vector_store is not None:
            try:
                vector_candidates = await self.vector_store.search(user_task, top_k)
                filtered = [
                    c
                    for c in vector_candidates
                    if not self._is_polluted_skill(c.get("skill_name", ""))
                ]
                if len(filtered) < len(vector_candidates):
                    logger.info(
                        _skrt_t(
                            "skrt.log.filtered_n",
                            n=len(vector_candidates) - len(filtered),
                        )
                    )
                candidates.extend(filtered)
            except Exception as e:
                logger.warning(_skrt_t("skrt.warn.vec_fallback", e=e))

        if len(candidates) < top_k:
            fallback = await self._fallback_keyword_match(user_task, top_k)
            candidates.extend(fallback)

        return candidates[:top_k]

    async def _fallback_keyword_match(self, user_task: str, top_k: int) -> List[Dict]:
        """关键词匹配回退方案（增强版 + 污染过滤）"""
        all_metadata = await self.memory.retrieve_recent(
            domain="skill_metadata", limit=200, chat_id="system"
        )

        if not all_metadata and self.evolution_engine:
            logger.debug(_skrt_t("skrt.debug.meta_empty"))
            all_skills = self.evolution_engine.get_all_skills()
            all_metadata = []
            for skill in all_skills:
                all_metadata.append(
                    {
                        "skill_name": skill["name"],
                        "versions": {"v1.0": {"description": ""}},
                        "current_version": "v1.0",
                    }
                )
            if not all_metadata:
                return []

        filtered_metadata = [
            meta for meta in all_metadata if not self._is_polluted_skill(meta.get("skill_name", ""))
        ]
        if len(filtered_metadata) < len(all_metadata):
            logger.info(
                _skrt_t(
                    "skrt.log.filtered_n",
                    n=len(all_metadata) - len(filtered_metadata),
                )
            )

        all_metadata = filtered_metadata

        task_words = set(user_task.lower().split())
        additional = set()
        for word in task_words:
            if word in self._synonym_map:
                additional.add(self._synonym_map[word])
        task_words.update(additional)

        task_words = {w for w in task_words if w not in self._stopwords and len(w) > 1}

        scored = []
        for meta in all_metadata:
            skill_name = meta.get("skill_name", "").lower()
            versions = meta.get("versions", {})
            current_ver = meta.get("current_version", "v1.0")
            version_info = versions.get(current_ver, {})
            description = version_info.get("description", "").lower()

            score = 0
            if any(word in skill_name for word in task_words):
                score += 2
            if any(word in description for word in task_words):
                score += 1

            if score > 0:
                scored.append((score, meta))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [meta for _, meta in scored[:top_k]]

    async def _decide_and_extract(self, user_task: str, candidates: List[Dict]) -> Optional[Dict]:
        """
        LLM 最终决断 + 通用参数补全。
        【步骤4 增强】：明确支持 Anthropic Skills（最高优先级 + prompt_template 直接注入）
        """
        if not candidates or not self.evolution_engine:
            return {"matched": False}

        skills_desc = []
        for c in candidates:
            skill_name = c.get("skill_name", "unknown")
            source = c.get("source", "unknown")
            description = c.get("description", "")
            prompt_template = c.get("prompt_template", "")
            required_params = c.get("required_params", []) or []

            if source == "anthropic-official":
                req = (
                    ", ".join(required_params)
                    if required_params
                    else i18n_t("sr.anthropic.none_params")
                )
                skills_desc.append(
                    i18n_t(
                        "sr.anthropic.block",
                        skill_name=skill_name,
                        desc=description[:120],
                        req=req,
                        preview=prompt_template[:80],
                    )
                )
            else:
                tool_info = self.evolution_engine.tool_schemas.get(skill_name, {})
                schema = tool_info.get("json_schema", {})
                properties = schema.get("properties", {})
                params_desc = ", ".join(
                    [f"{k}: {v.get('description', '')}" for k, v in properties.items()]
                )
                if params_desc:
                    skills_desc.append(
                        i18n_t(
                            "sr.skill.line_params", skill_name=skill_name, params_desc=params_desc
                        )
                    )
                else:
                    skills_desc.append(i18n_t("sr.skill.line_plain", skill_name=skill_name))

        prompt = i18n_t(
            "sr.llm.route_header",
            user_task=user_task,
            skills_block=chr(10).join(skills_desc),
        )

        logger.debug(_skrt_t("skrt.debug.llm_prompt_len", n=len(prompt)))
        try:
            response = await self.llm_router.call_llm(prompt, brain_type="action", temperature=0.1)
            data = extract_json_from_llm_output(response)
            if not data or not data.get("matched"):
                return {"matched": False}

            skill_name = data["skill_name"]
            args = data.get("args", {})

            if any(
                c.get("source") == "anthropic-official" and c.get("skill_name") == skill_name
                for c in candidates
            ):
                chosen = next(
                    (
                        c
                        for c in candidates
                        if c.get("source") == "anthropic-official"
                        and c.get("skill_name") == skill_name
                    ),
                    None,
                )
                if chosen:
                    args = args if isinstance(args, dict) else {}
                    args["__skill_source"] = "anthropic-official"
                    args["__prompt_template"] = chosen.get("prompt_template", "")
                    args["__required_params"] = chosen.get("required_params", []) or []
                return {"matched": True, "skill_name": skill_name, "args": args}

            tool_info = self.evolution_engine.tool_schemas.get(skill_name, {})
            required_params = tool_info.get("required_params", [])
            schema = tool_info.get("json_schema", {})
            required = schema.get("required", required_params)

            missing = [p for p in required if p not in args or args[p] is None or args[p] == ""]
            if missing:
                logger.info(_skrt_t("skrt.log.missing_params", name=skill_name, missing=missing))
                completion_prompt = i18n_t(
                    "sr.llm.completion_prompt",
                    user_task=user_task,
                    skill_name=skill_name,
                    args=str(args),
                    missing=str(missing),
                )
                completion_response = await self.llm_router.call_llm(
                    completion_prompt, brain_type="action", temperature=0.1
                )
                completion_data = extract_json_from_llm_output(completion_response)
                if completion_data and isinstance(completion_data, dict):
                    new_args = completion_data.get("args", {})
                    args.update(new_args)
                    logger.info(_skrt_t("skrt.log.args_after", args=args))
                else:
                    logger.warning(_skrt_t("skrt.warn.args_incomplete", missing=missing))
                    return {"matched": False}

            missing_final = [
                p for p in required if p not in args or args[p] is None or args[p] == ""
            ]
            if missing_final:
                logger.warning(_skrt_t("skrt.warn.args_still_missing", missing=missing_final))
                return {"matched": False}

            return {"matched": True, "skill_name": skill_name, "args": args}

        except Exception as e:
            logger.error(_skrt_t("skrt.err.llm_route", e=e))
            return {"matched": False}

    def set_vector_store(self, vector_store):
        """注入向量存储实例"""
        self.vector_store = vector_store


# --- END OF FILE skill_router.py ---
