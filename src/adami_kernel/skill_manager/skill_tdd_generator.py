# src/adami_kernel/skill_manager/skill_tdd_generator.py
"""
AdamI Skill Manager - SkillTDDGenerator（第四阶段核心组件）

负责为优化后的技能自动生成完整的 pytest 测试用例。
支持 async 测试、外部 API Mock、参数边界测试、异常场景覆盖。
输出可直接保存为 tests/test_{skill_name}.py，供 SelfTestEngine 执行。
【生产级设计】：结构化 Prompt + 严格格式校验 + 安全 Mock + 可扩展 Fixture
【步骤1 核心重构】：TDD 生成器改为异步后置任务，由 SkillBuilder 后台调度，不再阻塞主链路
"""

import logging
import re

from adami_kernel.config import settings
from adami_kernel.cortex.router import LLMRouter
from adami_kernel.i18n import t as i18n_t
from adami_kernel.i18n.boot_msg import boot_t

logger = logging.getLogger("AdamI-SkillTDDGenerator")


def _stdd_t(key: str, **kwargs: object) -> str:
    return i18n_t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class SkillTDDGenerator:
    """
    TDD 测试用例自动生成器（工业级）
    【步骤1 重构】：现在仅负责生成测试用例，由 SkillBuilder 异步后台任务调用
    """

    def __init__(self, router: LLMRouter):
        self.router = router
        logger.info(boot_t("boot.log.skill_tdd_init"))

    async def generate_test_cases(self, skill_name: str, code: str, description: str = "") -> str:
        """
        根据技能代码和描述，生成完整的 pytest 测试文件内容
        【步骤1 异步后置】：此方法由 SkillBuilder 的后台任务调用，不会阻塞用户主流程
        返回可直接写入 tests/test_{skill_name}.py 的完整代码
        """
        logger.info(_stdd_t("stdd.log.start", skill_name=skill_name))

        prompt = _stdd_t(
            "stdd.prompt.body",
            skill_name=skill_name,
            description=description,
            code=code,
            skill_lower=skill_name.lower(),
        )

        try:
            response = await self.router.call_llm(
                prompt, brain_type="think", temperature=0.1, max_tokens=4096
            )

            # 提取干净代码块
            cleaned = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL)
            cleaned = re.sub(r"^```(?:python)?\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.IGNORECASE).strip()

            if not cleaned or len(cleaned) < 200:
                logger.error(_stdd_t("stdd.log.too_short", skill_name=skill_name))
                return self._get_minimal_safe_template(skill_name, code)

            logger.info(_stdd_t("stdd.log.ok", skill_name=skill_name, n=len(cleaned)))
            return cleaned

        except Exception as e:
            logger.error(_stdd_t("stdd.log.fail", err=e))
            return self._get_minimal_safe_template(skill_name, code)

    def _get_minimal_safe_template(self, skill_name: str, code: str) -> str:
        """最小安全兜底模板"""
        d0 = _stdd_t("stdd.min.doc_execute")
        d1 = _stdd_t("stdd.min.doc_basic")
        d2 = _stdd_t("stdd.min.doc_error")
        sl = skill_name.lower()
        return f'''import asyncio
import pytest
from unittest.mock import patch, AsyncMock

async def execute(**kwargs):
    """{d0}"""
{code}

@pytest.mark.asyncio
async def test_{sl}_basic():
    """{d1}"""
    result = await execute()
    assert result is not None
    assert isinstance(result, dict)

@pytest.mark.asyncio
async def test_{sl}_error_handling():
    """{d2}"""
    with pytest.raises(Exception):
        await execute(invalid_param="test")
'''


# --- END OF FILE src/adami_kernel/skill_manager/skill_tdd_generator.py ---
