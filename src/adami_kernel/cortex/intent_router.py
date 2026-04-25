# src/adami_kernel/cortex/intent_router.py
import json
import logging
import re
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Pattern, Tuple

from adami_kernel.config import settings
from adami_kernel.i18n import t

logger = logging.getLogger("AdamI-IntentRouter")

_BUNDLE_PATH = (
    Path(__file__).resolve().parents[1] / "i18n" / "data" / "intent_router_regex_bundle.json"
)


@lru_cache(maxsize=1)
def _intent_regex_bundle() -> Dict[str, Any]:
    raw = _BUNDLE_PATH.read_text(encoding="utf-8")
    return json.loads(raw)


@lru_cache(maxsize=1)
def _compiled_task_note_pattern() -> Pattern[str]:
    return re.compile(_intent_regex_bundle()["task_note"], re.IGNORECASE)


def extract_task_note_body(text: str) -> str:
    """去掉 TASK_NOTE 触发前缀，得到写入 tasks.md 的正文（无匹配则返回 strip 后的原文）。"""
    raw = (text or "").strip()
    if not raw:
        return ""
    m = _compiled_task_note_pattern().match(raw)
    if not m:
        return raw
    g2 = m.group(2)
    if g2 is not None:
        return str(g2).strip()
    g4 = m.group(4)
    if g4:
        return str(g4).strip()
    return ""


def _ir_msg(key: str, **kwargs: Any) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class IntentSystemToken(str, Enum):
    """系统指令固定 token（与 `system_patterns` 键一致，供上游 Maintain/Writing 等识别与路由）。"""

    MAINTAIN = "MAINTAIN"
    WRITING = "WRITING"
    TASK_NOTE = "TASK_NOTE"
    REPORT = "REPORT"


class SemanticIntentRouter:
    """
    快慢双脑意图网络（System 1 极速反射弧）
    V3-Hybrid 最终版：百科全书式漏斗短路器 + 预编译正则 + 强制安全拦截
    【本次核心修复】：强化快脑 Prompt + 极致输出清洗（防复读、防停止符尾巴）
    【阶段3 集成】：新增 DIGEST 系统指令（/digest / 整理偏好 / 消化候选池 / 更新偏好）
    【阶段4 集成】：新增 INTAKE 系统指令 + 自动长文本知识摄入检测（>100字符自动触发 INTAKE_AUTO）
    【本次修改】：新增 FORCE_OPTIMIZE 精确路由，直接调用 SkillOptimizer.optimize()
    【小条4】：MAINTAIN（/maintain、维护、全库诊断）与 WRITING（/writing、/写作、单独「写作」、或「写作：…」）与 REPORT（/report…、或「报告/报表」后接子命令）固定 token（见 IntentSystemToken）；避免以「写作/报告」开头的普通长句误触系统指令（见 intent_router_regex_bundle.json）
    【步骤15】：TASK_NOTE（帮我记一下、记任务等）→ SYSTEM_ACTION，供下游写入 tasks.md

    Tier-two **rule-only** hints for planner-bound traffic live in
    ``adami_kernel.cortex.intent_adaptive.rule_classifier`` (``rule_classify_after_router``);
    that module runs **after** ``route_task`` and does not alter routing inside this class.
    """

    def __init__(self, llm_router):
        self.router = llm_router
        logger.debug(_ir_msg("ir.log.router_bind"))

        b = _intent_regex_bundle()
        self.sensitive_patterns: List[Pattern[str]] = [
            re.compile(p, re.IGNORECASE) for p in b["sensitive"]
        ]
        self.realtime_patterns: List[Pattern[str]] = [
            re.compile(p, re.IGNORECASE) for p in b["realtime"]
        ]
        self.complex_patterns: List[Pattern[str]] = [
            re.compile(p, re.IGNORECASE) for p in b["complex"]
        ]
        self.fast_patterns: List[Pattern[str]] = [re.compile(p, re.IGNORECASE) for p in b["fast"]]
        self._re_translate = re.compile(b["fast"][2], re.IGNORECASE)
        self._re_intro = re.compile(b["helpers"]["intro_trigger"], re.IGNORECASE)

        self.system_patterns: Dict[str, Pattern[str]] = {}
        for k, v in b["system"].items():
            self.system_patterns[k] = re.compile(v, re.IGNORECASE)
        self.system_patterns[IntentSystemToken.TASK_NOTE.value] = _compiled_task_note_pattern()

    async def route_task(self, task_text: str) -> Tuple[str, Any]:
        """主入口：漏斗式意图拦截路由"""
        task = task_text.strip()

        for pattern in self.sensitive_patterns:
            if pattern.search(task):
                logger.warning(_ir_msg("ir.warn.sensitive"))
                return ("COMPLEX_TASK", None)

        for pattern in self.realtime_patterns:
            if pattern.search(task):
                logger.info(_ir_msg("ir.log.realtime"))
                return ("COMPLEX_TASK", None)

        force_match = self.system_patterns["FORCE_OPTIMIZE"].search(task)
        if force_match:
            skill_name = force_match.group(2)
            if skill_name:
                skill_name = skill_name.upper().strip()
                logger.info(_ir_msg("ir.log.force_opt", name=skill_name))
                return ("SYSTEM_ACTION", ("FORCE_OPTIMIZE", skill_name))
            logger.warning(_ir_msg("ir.warn.force_opt_noname"))
            return ("DIRECT_ANSWER", _ir_msg("ir.msg.force_optimize_need_skill"))

        for cmd, pattern in self.system_patterns.items():
            if cmd == "FORCE_OPTIMIZE":
                continue
            if pattern.search(task):
                logger.info(_ir_msg("ir.log.sys_cmd", cmd=cmd))
                if cmd == IntentSystemToken.TASK_NOTE.value:
                    logger.info(_ir_msg("ir.log.task_note"))
                return ("SYSTEM_ACTION", cmd)

        if len(task) > 100 and not any(p.search(task) for p in self.complex_patterns):
            logger.info(_ir_msg("ir.log.intake_auto", n=len(task)))
            return ("SYSTEM_ACTION", "INTAKE_AUTO")

        for pattern in self.complex_patterns:
            if pattern.search(task):
                logger.info(_ir_msg("ir.log.complex_fast"))
                return ("COMPLEX_TASK", None)

        for pattern in self.fast_patterns:
            if pattern.search(task):
                logger.info(_ir_msg("ir.log.fast_hit"))
                return await self._generate_fast_answer(task)

        logger.info(_ir_msg("ir.log.hybrid_fuzzy"))
        fast_prompt = _ir_msg("ir.prompt.fast_router", task=task)

        try:
            response = await self.router.call_llm(
                fast_prompt,
                brain_type="action",
                temperature=0.1,
                timeout=8,
                apply_design_output_policy=True,
            )
            response = response.strip()

            if "[COMPLEX_TASK]" in response:
                logger.info(_ir_msg("ir.log.hybrid_complex"))
                return ("COMPLEX_TASK", None)
            answer = response.replace("[DIRECT_ANSWER]", "").strip()
            answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL)
            answer = answer.split("<|endoftext|>")[0].split("<|im_start|>")[0].strip()
            answer = re.sub(r"(.{4,}?)\1{2,}", r"\1", answer)
            logger.info(_ir_msg("ir.log.hybrid_direct"))
            return ("DIRECT_ANSWER", answer or _ir_msg("ir.msg.received_ok"))

        except Exception as e:
            logger.warning(_ir_msg("ir.warn.hybrid_fail", e=e))
            return ("COMPLEX_TASK", None)

    async def _generate_fast_answer(self, task: str) -> Tuple[str, Any]:
        """专门为命中 fast_patterns 的极简任务直接生成答案"""
        translate_match = self._re_translate.search(task)
        if translate_match:
            text_to_translate = translate_match.group(2).strip()
            if text_to_translate:
                prompt = _ir_msg("ir.prompt.translate_strict", text_to_translate=text_to_translate)

                try:
                    response = await self.router.call_llm(
                        prompt,
                        brain_type="action",
                        temperature=0.0,
                        max_tokens=300,
                        timeout=6,
                        apply_design_output_policy=True,
                    )
                    translation = response.strip()
                    translation = re.sub(r"<think>.*?</think>", "", translation, flags=re.DOTALL)
                    translation = (
                        translation.split("<|endoftext|>")[0].split("<|im_start|>")[0].strip()
                    )
                    translation = re.sub(r"^[,，\s]+", "", translation)
                    translation = re.sub(r"(.+)\1+", r"\1", translation)
                    logger.info(_ir_msg("ir.log.translate_len", n=len(translation)))
                    return ("DIRECT_ANSWER", translation or text_to_translate)
                except Exception as e:
                    logger.warning(_ir_msg("ir.warn.translate_llm", e=e))
                    return (
                        "DIRECT_ANSWER",
                        _ir_msg("ir.msg.translate_failed", text=text_to_translate),
                    )

        if self._re_intro.search(task):
            prompt = _ir_msg("ir.prompt.self_intro")
            try:
                response = await self.router.call_llm(
                    prompt,
                    brain_type="action",
                    temperature=0.0,
                    max_tokens=150,
                    timeout=5,
                    apply_design_output_policy=True,
                )
                intro = re.sub(r"<think>.*?</think>", "", response.strip(), flags=re.DOTALL)
                intro = intro.split("<|endoftext|>")[0].split("<|im_start|>")[0].strip()
                return ("DIRECT_ANSWER", intro or _ir_msg("ir.fallback.self_intro"))
            except Exception as e:
                logger.warning(_ir_msg("ir.warn.intro_llm", e=e))
                return ("DIRECT_ANSWER", _ir_msg("ir.fallback.self_intro"))

        prompt = _ir_msg("ir.prompt.short_answer", task=task)
        try:
            response = await self.router.call_llm(
                prompt,
                brain_type="action",
                temperature=0.0,
                max_tokens=200,
                timeout=5,
                apply_design_output_policy=True,
            )
            answer = re.sub(r"<think>.*?</think>", "", response.strip(), flags=re.DOTALL)
            answer = answer.split("<|endoftext|>")[0].split("<|im_start|>")[0].strip()
            return ("DIRECT_ANSWER", answer or _ir_msg("ir.msg.checkmark_only"))
        except Exception as e:
            logger.warning(_ir_msg("ir.warn.fast_path_fail", e=e))
            return ("COMPLEX_TASK", None)


# End of src/adami_kernel/cortex/intent_router.py
