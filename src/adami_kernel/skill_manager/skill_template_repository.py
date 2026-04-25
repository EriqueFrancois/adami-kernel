# --- START OF FILE skill_template_repository.py ---
"""
AdamI Skill Manager - SkillTemplateRepository（模板优先策略）

维护预置优质模板库，根据任务描述关键词匹配返回完整、可直接运行的模板代码。
【本次核心修复】：price 模板更换为免费无限制的 CoinCap API，weather 错误提示更友好。
"""

import json
import logging
import textwrap
from pathlib import Path
from typing import Dict, Optional

from adami_kernel.config import settings
from adami_kernel.i18n import t as i18n_t
from adami_kernel.i18n.catalog import _read_json_string_dict
from adami_kernel.i18n.locale_utils import normalize_locale

logger = logging.getLogger("AdamI-SkillTemplateRepository")


def _stpl_t(key: str, **kwargs: object) -> str:
    return i18n_t(key, locale=settings.effective_ui_default_locale(), **kwargs)


def _stpl_catalog_raw(key: str) -> str:
    """
    读取模板用文案但不走 ``str.format``：嵌入技能源码的字符串里常含 ``{status_code}`` 等占位符，
    留给生成后的 ``execute`` 在运行时 ``.format()``；若走 ``i18n_t`` 会在构建模板阶段缺参报错。
    """
    loc = normalize_locale(settings.effective_ui_default_locale())
    root = Path(__file__).resolve().parents[1] / "i18n" / "locales"
    for cand in (loc, "en"):
        path = root / cand / "common.json"
        m = _read_json_string_dict(path)
        if key in m:
            return m[key]
    return key


def _build_templates() -> Dict[str, str]:
    Z = _stpl_catalog_raw
    e_no = json.dumps(Z("stpl.weather.err_no_city"), ensure_ascii=False)
    e_cong = json.dumps(Z("stpl.weather.err_congest"), ensure_ascii=False)
    e_ct = json.dumps(Z("stpl.weather.err_connect_timeout"), ensure_ascii=False)
    e_net = json.dumps(Z("stpl.weather.err_net"), ensure_ascii=False)
    ok_price = json.dumps(Z("stpl.price.success"), ensure_ascii=False)
    e_pf = json.dumps(Z("stpl.price.err_fetch"), ensure_ascii=False)
    e_pt = json.dumps(Z("stpl.price.err_timeout"), ensure_ascii=False)
    e_pn = json.dumps(Z("stpl.price.err_net"), ensure_ascii=False)

    weather = textwrap.dedent(
        f"""
            city = kwargs.get("city", "")
            if not city:
                return {{"status": "error", "error": {e_no}}}
            try:
                async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                    resp = await client.get(f"https://wttr.in/{{city}}?format=%C+%t&lang=zh")
                    if resp.status_code == 200:
                        return {{"status": "success", "data": resp.text.strip()}}
                    else:
                        msg = {e_cong}.format(status_code=resp.status_code)
                        return {{"status": "error", "error": msg}}
            except httpx.ConnectTimeout:
                return {{"status": "error", "error": {e_ct}}}
            except Exception as e:
                err = str(e)
                if err:
                    return {{"status": "error", "error": err}}
                msg = {e_net}.format(exc_name=type(e).__name__)
                return {{"status": "error", "error": msg}}
        """
    ).strip()

    price = textwrap.dedent(
        f"""
            coin = kwargs.get("coin", "bitcoin")
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
                            msg = {ok_price}.format(coin=coin_id.upper(), amount=f"{{float(price):.2f}}")
                            return {{"status": "success", "data": msg}}
                    msg = {e_pf}.format(coin_id=coin_id, status_code=resp.status_code)
                    return {{"status": "error", "error": msg}}
            except httpx.ConnectTimeout:
                return {{"status": "error", "error": {e_pt}}}
            except Exception as e:
                msg = {e_pn}.format(err=e)
                return {{"status": "error", "error": msg}}
        """
    ).strip()

    return {"weather": weather, "price": price}


class SkillTemplateRepository:
    """
    技能模板仓库（模板优先策略）
    """

    _TEMPLATES: Optional[Dict[str, str]] = None

    @classmethod
    def _templates(cls) -> Dict[str, str]:
        if cls._TEMPLATES is None:
            cls._TEMPLATES = _build_templates()
        return cls._TEMPLATES

    @classmethod
    def clear_template_cache(cls) -> None:
        """测试或切换 UI 语言后重建内存模板（避免沿用旧 ``_stpl_t`` 构建结果）。"""
        cls._TEMPLATES = None

    @staticmethod
    def get_template(task_description: str, skill_name: str = "") -> Optional[str]:
        """
        根据任务描述和技能名称匹配预置模板。
        """
        desc_lower = f"{task_description.lower()} {skill_name.lower()}"
        w_kw = json.loads(_stpl_t("stpl.match.weather_keywords_json"))
        p_kw = json.loads(_stpl_t("stpl.match.price_keywords_json"))

        if any(kw in desc_lower for kw in w_kw):
            logger.info(_stpl_t("stpl.log.match_weather"))
            return SkillTemplateRepository._templates()["weather"]

        if any(kw in desc_lower for kw in p_kw):
            logger.info(_stpl_t("stpl.log.match_price"))
            return SkillTemplateRepository._templates()["price"]

        return None


# --- END OF FILE skill_template_repository.py ---
