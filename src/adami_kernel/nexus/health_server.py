import logging

import psutil
from aiohttp import web

# ====================== 【Bug 1 核心修复】使用统一配置中心 ======================
from adami_kernel.config import settings
from adami_kernel.i18n import t
from adami_kernel.i18n.boot_msg import boot_t

# =================================================================================

logger = logging.getLogger("AdamI-HealthServer")


def _nhsrv_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class HealthServer:
    def __init__(self, kernel):
        self.kernel = kernel
        # 【Bug 1 + Bug 10 修复】使用统一配置 + 保存 runner 引用
        self.port = settings.ADAMI_HEALTH_PORT
        self.runner = None

    async def start(self):
        async def policy_version_handler(request):
            """只读：当前策略 manifest 版本（双实例对账 / 运维探针）。"""
            from adami_kernel.policy.loader import get_policy_loader

            pl = get_policy_loader()
            if pl is None:
                return web.json_response(
                    {"loaded": False, "version": None, "optional_model_ref": None}
                )
            m = pl.get_manifest()
            if m is None:
                return web.json_response(
                    {
                        "loaded": False,
                        "version": None,
                        "optional_model_ref": None,
                    }
                )
            return web.json_response(
                {
                    "loaded": True,
                    "version": m.version,
                    "optional_model_ref": m.optional_model_ref,
                    "prompt_template_keys": list(m.prompt_template_paths.keys()),
                }
            )

        async def health_handler(request):
            status = {
                "status": "healthy",
                "modules": {
                    "dynamic_skills": len(self.kernel.evolution_engine.dynamic_skills),
                    "core_instincts": len(self.kernel.evolution_engine.core_instincts),
                    "telegram": bool(self.kernel.telegram_nerve),
                    "discord": bool(getattr(self.kernel, "discord_nerve", None)),
                    "proprioception": bool(self.kernel.proprioception),
                },
                # 【Bug 11 核心修复】CPU 使用率瞬时值不准确 → 使用 interval=1 获取真实平均负载
                "cpu_percent": psutil.cpu_percent(interval=1),
                "ram_percent": psutil.virtual_memory().percent,
                "running": self.kernel._running,
            }
            return web.json_response(status)

        app = web.Application()
        app.router.add_get("/health", health_handler)
        app.router.add_get("/policy/version", policy_version_handler)

        # ====================== 【Bug 25 + Bug 10 核心修复】保存 runner 引用 ======================
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "0.0.0.0", self.port)
        await site.start()
        # =================================================================================

        logger.info(boot_t("boot.log.health_http_started", port=self.port))

    # ====================== 【Bug 10 + Bug 25 核心修复】优雅关闭方法 ======================
    async def stop(self):
        """在 kernel 退出时调用，实现 runner 彻底清理（端口释放）"""
        if hasattr(self, "runner") and self.runner is not None:
            try:
                await self.runner.cleanup()
                logger.info(_nhsrv_t("nhsrv.log.shutdown", port=self.port))
            except Exception as e:
                logger.warning(_nhsrv_t("nhsrv.warn.shutdown", e=e))
        # =================================================================================
