import logging
from typing import Tuple

from adami_kernel.i18n.boot_msg import boot_t
from adami_kernel.orchestrator.loader import PluginLoader

logger = logging.getLogger("AdamI-ClawHub")


class ClawHub:
    """
    AdamI 技能市场生态系统 (ClawHub)
    负责连接开源社区，执行外源基因的搜索、下载、安全审计与投递。
    """

    def __init__(self, toolbox):
        self.toolbox = toolbox
        # 严格复用 AST 免疫系统，防止外源病毒 (如含有 os.system, rm -rf 的恶意插件)
        self.auditor = PluginLoader()

    async def search_skills(self, query: str) -> str:
        """在广袤的开源社区寻找合适的技能基因片段"""
        # 默认附加 python 限制以提高精确度
        full_query = f"{query} extension:py"
        logger.info(boot_t("boot.log.claw_searching", query=full_query))
        res = await self.toolbox.web.github_search_code(full_query)

        # 【核心修复】：拦截 Token 失效/过期，引导大模型改道
        if isinstance(res, dict) and res.get("status") == "error":
            msg = str(res.get("message", ""))
            if "401" in msg or "Bad credentials" in msg or "valid GITHUB_TOKEN" in msg:
                logger.warning(boot_t("boot.log.claw_github_token_warn"))
                return boot_t("cjk_gate.claw_github_token_warning")

        return res

    async def download_and_audit(self, raw_url: str) -> Tuple[bool, str, str]:
        """下载外源基因并经过严格的 AST 免疫检查"""
        logger.info(boot_t("boot.log.claw_downloading", url=raw_url))

        # 1. 获取纯净源码
        code = await self.toolbox.web.github_fetch_raw(raw_url)

        # 【核心修复】：兼容网络层返回字典格式（包括成功和失败的情况）
        if isinstance(code, dict):
            if code.get("status") == "success" and "content" in code:
                code_str = code["content"]
            else:
                return False, f"Download failed: {code.get('message', str(code))}", ""
        else:
            code_str = str(code)

        if "Error" in code_str or not code_str.strip() or "404: Not Found" in code_str:
            return False, f"Download failed or invalid URL: {code_str[:100]}", ""

        logger.info(boot_t("boot.log.claw_ast_audit_start"))

        # 2. 免疫系统静态检查
        if not self.auditor.audit_code(code_str):
            return False, boot_t("cjk_gate.claw_immune_block"), code_str

        logger.info(boot_t("boot.log.claw_ast_audit_ok"))
        return True, "Audit passed.", code_str
