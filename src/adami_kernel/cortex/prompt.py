# src/adami_kernel/cortex/prompt.py
import json
import logging
from typing import Any, Dict, List

from adami_kernel.config import settings
from adami_kernel.i18n import t as i18n_t

logger = logging.getLogger("AdamI-PromptBuilder")


def _cprm_t(key: str, **kwargs: Any) -> str:
    return i18n_t(key, locale=settings.effective_ui_default_locale(), **kwargs)


def _zh_chars(*hex4: str) -> str:
    return "".join(json.loads(f'"\\u{h.lower()}"') for h in hex4)


_CR = _zh_chars("521b", "5efa")
_SK = _zh_chars("6280", "80fd")
_MEOW_HINT = _zh_chars("55b5") + "~"


class PromptBuilder:
    """
    PromptBuilder（工业级提示词构建器）
    【阶段1 最终版】：支持 SecondBrainManager 动态注入身份上下文
    本次加强：增加详细日志 + 异常防护 + 强制注入，确保 PROFILE.md 热编辑立即生效
    """

    def __init__(
        self,
        system_persona: str,
        max_memory_tokens: int = 4000,
        second_brain=None,
        policy_loader=None,
    ) -> None:
        self.system_persona = system_persona
        self._max_memory_chars = max_memory_tokens * 2
        self.second_brain = second_brain  # 第二大脑管理器引用
        self.policy_loader = policy_loader
        logger.debug(
            _cprm_t(
                "cprm.debug.ready",
                sb="yes" if second_brain else "no",
                pl="yes" if policy_loader else "no",
            )
        )

    def _resolve_persona_base(self) -> str:
        """优先策略包 system 模板；否则 ``system_persona``。"""
        if self.policy_loader:
            templates = self.policy_loader.read_system_templates_from_disk()
            if templates:
                return templates
        return self.system_persona

    def _wrap_task_block(self, event_str: str, memory_section: str, recalled_errors: str) -> str:
        """可选 user_fragment 模板（占位 {event} / {memories} / {recalled_errors}）。"""
        base = _cprm_t("cprm.block.current_env", event_str=event_str)
        if not self.policy_loader:
            return base
        frag = self.policy_loader.read_user_fragment_from_disk()
        if not frag:
            return base
        if "{" in frag and "}" in frag:
            try:
                return (
                    frag.format(
                        event=event_str,
                        memories=memory_section,
                        recalled_errors=recalled_errors or "",
                    )
                    + "\n\n"
                )
            except KeyError:
                return f"{frag}\n\n{base}"
        return f"{frag}\n\n{base}"

    async def _format_memories(self, memories: List[Dict[str, Any]]) -> str:
        if not memories:
            return _cprm_t("cprm.mem.empty")
        formatted_str = _cprm_t("cprm.mem.header")
        for mem in reversed(memories[-5:]):
            formatted_str += f"- {json.dumps(mem, ensure_ascii=False)}\n"
        return formatted_str

    async def build_action_prompt(
        self,
        current_event: Dict[str, Any],
        retrieved_memories: List[Dict[str, Any]],
        recalled_errors: str = "",
    ) -> str:
        memory_section = await self._format_memories(retrieved_memories)

        ev = str(current_event).lower()
        is_creating_skill = _CR in ev and _SK in ev
        if not is_creating_skill:
            is_creating_skill = _CR in memory_section and _SK in memory_section

        event_str = json.dumps(current_event, ensure_ascii=False, indent=2)

        persona_text = self._resolve_persona_base()

        # 【阶段1 核心注入】动态读取 SecondBrain 身份上下文
        if self.second_brain:
            try:
                identity_context = self.second_brain.read_identity_context()
                persona_text = f"{persona_text}\n\n{identity_context}"
                logger.info(
                    _cprm_t("cprm.log.identity_inject", n=len(identity_context)),
                )
                if _MEOW_HINT in identity_context or "PROFILE.md" in identity_context:
                    logger.info(_cprm_t("cprm.log.profile_hint"))
                doctrine = self.second_brain.read_second_brain_doctrine()
                if doctrine:
                    persona_text = f"{persona_text}\n\n<SECOND_BRAIN_DOCTRINE>\n{doctrine}\n</SECOND_BRAIN_DOCTRINE>"
                    logger.info(
                        _cprm_t("cprm.log.doctrine_inject", n=len(doctrine)),
                    )
            except Exception as e:
                logger.error(_cprm_t("cprm.err.identity", e=e), exc_info=True)
        else:
            logger.warning(_cprm_t("cprm.warn.no_secondbrain"))

        # Optional retrieval-priority hint (Phase 1.6.2): one i18n line, gated by settings + SecondBrain presence.
        if settings.ADAMI_PROMPT_KNOWLEDGE_WIKI_HINT and self.second_brain:
            persona_text = f"{persona_text}\n\n{_cprm_t('cprm.hint.knowledge_wiki_priority')}"

        if settings.ADAMI_PROMPT_OUTPUT_EXAMPLES_REPORT_HINT and self.second_brain:
            persona_text = f"{persona_text}\n\n{i18n_t('doc.pipeline.output_examples_report', locale=settings.effective_ui_default_locale())}"

        if is_creating_skill:
            strip_kw = json.loads(_cprm_t("cprm.strip.line_keywords_json"))
            lines = []
            for line in persona_text.split("\n"):
                if any(keyword in line for keyword in strip_kw):
                    continue
                lines.append(line)
            persona_text = "\n".join(lines)
            persona_text += _cprm_t("cprm.skill.force_banner")

        task_block = self._wrap_task_block(event_str, memory_section, recalled_errors)

        prompt = (
            _cprm_t("cprm.fmt.persona_head", persona_text=persona_text)
            + f"{memory_section}\n\n"
            + f"{recalled_errors}\n\n"
            + f"{task_block}"
            + _cprm_t("cprm.tail.static_manual")
        )
        return prompt
