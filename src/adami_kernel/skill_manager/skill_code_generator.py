# src/adami_kernel/skill_manager/skill_code_generator.py
"""
AdamI Skill Manager - 代码生成器模块

本模块集中存放代码生成相关方法（任务类型检测 + LLM / 硬编码生成）。
【本次 v2.2 核心修复】：fallback 模板彻底移除未定义变量 'skill_name'，防止 SkillInspector NameError
"""

import json
import logging
import re
import textwrap
from typing import Any, Optional

from adami_kernel.config import settings
from adami_kernel.i18n import t
from adami_kernel.skill_manager.skill_template_repository import SkillTemplateRepository

logger = logging.getLogger("AdamI-SkillCodeGenerator")


def _skcg_t(key: str, **kwargs: Any) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


def _uchars(*hex4: str) -> str:
    return "".join(json.loads(f'"\\u{h.lower()}"') for h in hex4)


class SkillCodeGenerator:
    """
    技能代码生成器
    【v2.2 核心修复】：fallback 模板完全静态化 + NameError 防护
    """

    def __init__(self, router, template_repo: Optional[SkillTemplateRepository] = None):
        self.router = router
        self.template_repo = template_repo or SkillTemplateRepository()
        logger.info(_skcg_t("skcg.log.init"))

    def _detect_task_type(self, description: str, skill_name: str = "") -> str:
        """任务类型检测（联合 skill_name 检测，防止失忆）"""
        desc_lower = f"{description.lower()} {skill_name.lower()}"

        if any(
            kw in desc_lower
            for kw in (
                _uchars("5929", "6c14"),
                "weather",
                _uchars("6c14", "6e29"),
                "temperature",
                _uchars("67e5", "8be2", "5929", "6c14"),
            )
        ):
            return "weather"
        if any(
            kw in desc_lower
            for kw in (
                _uchars("4ef7", "683c"),
                "price",
                "btc",
                "eth",
                "sol",
                _uchars("6bd4", "7279", "5e01"),
                _uchars("4ee5", "592a", "574a"),
                _uchars("7d22", "62c9", "7eb3"),
                "crypto",
                _uchars("5e01", "4ef7"),
                _uchars("6570", "5b57", "8d27", "5e01"),
            )
        ):
            return "price"
        return "general"

    def _wrap_with_standard_imports_and_execute(self, body_code: str) -> str:
        """
        强制包裹标准 import + 完整 execute 函数
        """
        standard_imports = textwrap.dedent("""\
            import asyncio
            import datetime
            import time
            import json
            import httpx
            from typing import Any, Dict
        """).strip()

        doc_txt = _skcg_t("skcg.wrap.execute_doc")
        fb_err = json.dumps(_skcg_t("skcg.wrap.fallback_no_return"), ensure_ascii=False)
        full_code = f"""{standard_imports}

async def execute(**kwargs: Any) -> Dict[str, Any]:
    \"\"\"{doc_txt}\"\"\"
{textwrap.indent(body_code.strip(), "    ")}

    return {{"status": "error", "error": {fb_err}}}
"""
        return textwrap.dedent(full_code).strip()

    async def generate_code(self, description: str, skill_name: str) -> str:
        """公开生成入口（推荐调用此方法）"""
        return await self._generate_code_from_description(description, skill_name)

    async def _generate_code_from_description(self, description: str, skill_name: str) -> str:
        """内部生成逻辑"""
        if self.template_repo:
            template_code = self.template_repo.get_template(description, skill_name)
            if template_code:
                logger.info(_skcg_t("skcg.log.template_hit", name=skill_name))
                return self._wrap_with_standard_imports_and_execute(template_code)

        task_type = self._detect_task_type(description, skill_name)

        if task_type == "weather":
            logger.info(_skcg_t("skcg.log.weather_tpl"))
            _e_city = json.dumps(_skcg_t("skcg.runtime.err_need_city"), ensure_ascii=False)
            _e_busy = repr(_skcg_t("skcg.runtime.err_weather_busy"))
            _e_to = json.dumps(_skcg_t("skcg.runtime.err_weather_timeout"), ensure_ascii=False)
            _e_net = repr(_skcg_t("skcg.runtime.err_network_exc"))
            body_code = f"""
city = kwargs.get('city')
if not city:
    return {{"status": "error", "error": {_e_city}}}
try:
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        resp = await client.get(f"https://wttr.in/{{city}}?format=%C+%t&lang=zh")
        if resp.status_code == 200:
            return {{"status": "success", "data": resp.text.strip()}}
        else:
            return {{"status": "error", "error": ({_e_busy}) % resp.status_code}}
except httpx.ConnectTimeout:
    return {{"status": "error", "error": {_e_to}}}
except Exception as e:
    error_msg = str(e) if str(e) else (({_e_net}) % (type(e).__name__,))
    return {{"status": "error", "error": error_msg}}
"""
            return self._wrap_with_standard_imports_and_execute(body_code)

        if task_type == "price":
            logger.info(_skcg_t("skcg.log.price_tpl"))
            _ok = repr(_skcg_t("skcg.runtime.price_ok_pat"))
            _ef = repr(_skcg_t("skcg.runtime.err_price_fetch_pat"))
            _eto = json.dumps(_skcg_t("skcg.runtime.err_price_timeout"), ensure_ascii=False)
            _enet = repr(_skcg_t("skcg.runtime.err_price_network"))
            body_code = f"""
coin = kwargs.get('coin', 'bitcoin')
coin_map = {{
    "btc": "bitcoin", "eth": "ethereum", "sol": "solana", "doge": "dogecoin"
}}
coin_id = coin_map.get(coin.lower(), coin.lower())
try:
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        url = f"https://api.coincap.io/v2/assets/{{coin_id}}"
        resp = await client.get(url)
        if resp.status_code == 200:
            data = resp.json()
            price = data.get("data", {{}}).get("priceUsd")
            if price is not None:
                return {{"status": "success", "data": ({_ok}) % (coin_id.upper(), float(price))}}
        return {{"status": "error", "error": ({_ef}) % (coin_id, resp.status_code)}}
except httpx.ConnectTimeout:
    return {{"status": "error", "error": {_eto}}}
except Exception as e:
    return {{"status": "error", "error": ({_enet}) % (e,)}}
"""
            return self._wrap_with_standard_imports_and_execute(body_code)

        if not self.router:
            logger.warning(_skcg_t("skcg.warn.no_router"))
            return self._wrap_with_standard_imports_and_execute(
                "return {'status': 'error', 'error': "
                + json.dumps(_skcg_t("skcg.runtime.router_uninit"))
                + "}"
            )

        logger.info(_skcg_t("skcg.log.general_llm"))

        # ==================== v2.2 核心修复：LLM 调用完全健壮化 ====================
        _ex_url = json.dumps(_skcg_t("skcg.runtime.err_need_url"), ensure_ascii=False)
        example_code = f"""
url = kwargs.get('url')
if not url:
    return {{"status": "error", "error": {_ex_url}}}
async with httpx.AsyncClient() as client:
    resp = await client.get(url)
    if resp.status_code == 200:
        return {{"status": "success", "data": resp.text[:1000]}}
return {{"status": "error", "error": f"HTTP {{resp.status_code}}"}}
"""

        prompt = _skcg_t("skcg.prompt.generate_body", description=description).replace(
            "__EXAMPLE_CODE__", example_code
        )

        try:
            response = await self.router.call_llm(prompt, brain_type="action", temperature=0.2)
            body_code = self.extract_python_code_from_llm_output(response)
            if not body_code.strip():
                logger.warning(_skcg_t("skcg.warn.llm_empty"))
                body_code = (
                    "return {'status': 'success', 'data': "
                    + json.dumps(_skcg_t("skcg.runtime.llm_empty_ok"))
                    + "}"
                )
        except Exception as e:
            logger.error(_skcg_t("skcg.err.llm", e=e))
            # v2.2 安全 fallback（完全静态，无任何未定义变量）
            body_code = (
                "return {'status': 'success', 'data': "
                + json.dumps(_skcg_t("skcg.runtime.llm_safe_mode"))
                + "}"
            )
        # =========================================================================

        # 强制包裹标准 import + execute
        return self._wrap_with_standard_imports_and_execute(body_code)

    def extract_python_code_from_llm_output(self, raw: str) -> str:
        """从 LLM 输出中提取 Python 代码"""
        raw = raw.strip()
        matches = re.findall(r"```python\s*(.*?)```", raw, re.DOTALL | re.IGNORECASE)
        if matches:
            return matches[-1].strip()
        matches = re.findall(r"```(?:py)?\s*(.*?)```", raw, re.DOTALL | re.IGNORECASE)
        if matches:
            return matches[-1].strip()
        match = re.search(r"async def execute.*?:(.*)", raw, re.DOTALL)
        if match:
            return match.group(1).strip()
        return raw
