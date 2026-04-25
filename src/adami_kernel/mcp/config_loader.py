from __future__ import annotations

import json
import logging
from typing import List

import adami_kernel.config as config_mod
from adami_kernel.i18n import t
from adami_kernel.mcp.spec import McpServerSpec

logger = logging.getLogger("AdamI-MCP")


def _mcpcfg_t(key: str, **kwargs) -> str:
    return t(key, locale=config_mod.settings.effective_ui_default_locale(), **kwargs)


def load_mcp_server_specs() -> List[McpServerSpec]:
    raw = config_mod.settings.ADAMI_MCP_SERVERS_JSON
    if not raw or not str(raw).strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning(_mcpcfg_t("mcpcfg.warn.json", e=e))
        return []
    if not isinstance(data, list):
        logger.warning(_mcpcfg_t("mcpcfg.warn.array"))
        return []

    out: List[McpServerSpec] = []
    seen: set[str] = set()
    for item in data:
        try:
            spec = McpServerSpec.model_validate(item)
        except Exception as e:
            logger.warning(_mcpcfg_t("mcpcfg.warn.spec", e=e))
            continue
        if spec.name in seen:
            logger.warning(_mcpcfg_t("mcpcfg.warn.dup", name=spec.name))
            continue
        seen.add(spec.name)
        out.append(spec)
    return out
