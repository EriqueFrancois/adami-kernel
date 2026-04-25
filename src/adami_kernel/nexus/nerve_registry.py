# src/adami_kernel/nexus/nerve_registry.py
import asyncio
import logging
from typing import Any, Dict, List, Optional

from adami_kernel.config import settings
from adami_kernel.i18n import t
from adami_kernel.i18n.boot_msg import boot_t
from adami_kernel.nexus.base_nerve import BaseNerve
from adami_kernel.nexus.discord_nerve import DiscordNerve

# TelegramSensory 保留 try-except 容错（下个文件会审计 component_initializer）
from adami_kernel.nexus.telegram_sensory import TelegramSensory

logger = logging.getLogger("AdamI-NerveRegistry")


def _nrv_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


def _digits_snowflake(value: object, *, field: str) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if not s.isdigit():
        raise RuntimeError(f"{field} must be a numeric snowflake string; got {value!r}")
    return s


def _validate_messenger_routing_settings() -> None:
    """
    Fail fast when a messenger token is enabled but routing defaults are missing.

    This intentionally runs at nerve registration time (kernel startup), not at Settings import time,
    so partially-configured developer .env files do not break importing the package / pytest collection.
    """
    tg_tok = str(getattr(settings, "TELEGRAM_BOT_TOKEN", "") or "").strip()
    if tg_tok:
        cid = getattr(settings, "TELEGRAM_CHAT_ID", None)
        if cid is None:
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN is set but TELEGRAM_CHAT_ID is missing. "
                "Set TELEGRAM_CHAT_ID (numeric chat id) or unset TELEGRAM_BOT_TOKEN to disable Telegram."
            )
        try:
            n = int(cid)  # type: ignore[arg-type]
        except Exception as e:
            raise RuntimeError(f"TELEGRAM_CHAT_ID must be int-like; got {cid!r}") from e
        if n <= 0:
            raise RuntimeError(
                "TELEGRAM_CHAT_ID must be a positive integer when TELEGRAM_BOT_TOKEN is set."
            )

    dc_tok = str(getattr(settings, "DISCORD_BOT_TOKEN", "") or "").strip()
    if dc_tok:
        uid = _digits_snowflake(
            getattr(settings, "DISCORD_DEFAULT_USER_ID", None), field="DISCORD_DEFAULT_USER_ID"
        )
        ch = _digits_snowflake(
            getattr(settings, "DISCORD_DEFAULT_CHANNEL_ID", None),
            field="DISCORD_DEFAULT_CHANNEL_ID",
        )
        gu = _digits_snowflake(
            getattr(settings, "DISCORD_DEFAULT_GUILD_ID", None), field="DISCORD_DEFAULT_GUILD_ID"
        )
        slash = _digits_snowflake(
            getattr(settings, "DISCORD_SLASH_GUILD_ID", None), field="DISCORD_SLASH_GUILD_ID"
        )
        if not (uid or ch or gu):
            raise RuntimeError(
                "DISCORD_BOT_TOKEN is set but no Discord routing defaults are configured. "
                "Set at least one of DISCORD_DEFAULT_USER_ID (recommended), DISCORD_DEFAULT_CHANNEL_ID, "
                "or DISCORD_DEFAULT_GUILD_ID — or unset DISCORD_BOT_TOKEN to disable Discord."
            )
        # Normalize optional fields to validated strings (or None).
        settings.DISCORD_DEFAULT_USER_ID = uid
        settings.DISCORD_DEFAULT_CHANNEL_ID = ch
        settings.DISCORD_DEFAULT_GUILD_ID = gu
        settings.DISCORD_SLASH_GUILD_ID = slash


def validate_messenger_routing_for_ops_check() -> None:
    """供运维自检等外部只读场景调用；与 ``register_default_nerves`` 内信使预检一致。"""
    _validate_messenger_routing_settings()


class NerveRegistry:
    """
    AdamI Nerve 注册中心（工业级最终版）
    - 自动注册所有内置 Nerve（Discord + Telegram）
    - 提供查询接口
    - 安全启动/停止 + 异常隔离
    - 【本次核心修复】：全链路详细日志 + 精确平台匹配 + publish_func 注入确认
    - 状态汇报
    """

    def __init__(self):
        self.nerves: List[BaseNerve] = []
        self._initialized = False
        logger.info(boot_t("boot.log.nerve_registry_init"))

    def register(self, nerve: BaseNerve) -> List[BaseNerve]:
        """注册单个 Nerve（供 ComponentInitializer 调用）"""
        if not nerve:
            return self.nerves
        self.nerves.append(nerve)
        logger.debug(_nrv_t("nrv.debug.registered", cls=nerve.__class__.__name__))
        return self.nerves

    def register_default_nerves(self, publish_func) -> None:
        """【核心修复】自动注册所有内置 Nerve + publish_func 注入确认"""
        if self._initialized:
            logger.debug(_nrv_t("nrv.debug.skip_init"))
            return
        self._initialized = True

        validate_messenger_routing_for_ops_check()

        # ====================== Discord Nerve ======================
        if getattr(settings, "DISCORD_BOT_TOKEN", None):
            try:
                discord_nerve = DiscordNerve(publish_func=publish_func)
                self.register(discord_nerve)
                logger.debug(_nrv_t("nrv.debug.discord_ok"))
            except Exception as e:
                logger.error(_nrv_t("nrv.err.discord_init", e=e), exc_info=True)
        else:
            logger.warning(_nrv_t("nrv.warn.discord_token"))

        # ====================== Telegram Sensory ======================
        if getattr(settings, "TELEGRAM_BOT_TOKEN", None):
            try:
                telegram_sensory = TelegramSensory(publish_func=publish_func)
                self.register(telegram_sensory)
                logger.debug(_nrv_t("nrv.debug.telegram_ok"))
            except Exception as e:
                logger.warning(_nrv_t("nrv.warn.telegram_init", e=e), exc_info=True)
        else:
            logger.warning(_nrv_t("nrv.warn.telegram_token"))

    def get_nerve(self, name: str) -> Optional[BaseNerve]:
        """按类名查找 Nerve"""
        for nerve in self.nerves:
            if nerve.__class__.__name__ == name:
                return nerve
        return None

    def get_nerve_by_platform(self, platform: str) -> Optional[BaseNerve]:
        """【核心修复】按平台精确查找 Nerve"""
        for nerve in self.nerves:
            # 精确类名匹配
            if platform == "discord" and isinstance(nerve, DiscordNerve):
                return nerve
            if platform == "telegram" and "Telegram" in nerve.__class__.__name__:
                return nerve
            # 通用 platform 属性匹配（未来扩展）
            if hasattr(nerve, "platform") and nerve.platform == platform:
                return nerve
        logger.warning(_nrv_t("nrv.warn.platform_not_found", platform=platform))
        return None

    @staticmethod
    async def _safe_task(coro):
        """为每个后台任务添加异常捕获"""
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception(_nrv_t("nrv.err.bg_task", e=e))

    async def start_all(self, background_tasks: List[asyncio.Task]) -> None:
        """启动所有 Nerve"""
        if not self.nerves:
            logger.warning(_nrv_t("nrv.warn.none_to_start"))
            return

        for nerve in self.nerves:
            if hasattr(nerve, "start_listening"):
                safe_coro = self._safe_task(nerve.start_listening())
                task = asyncio.create_task(safe_coro)
                background_tasks.append(task)
                logger.info(boot_t("boot.log.nerve_listening", name=nerve.__class__.__name__))

    async def stop_all(self) -> None:
        """优雅停止所有 Nerve"""
        for nerve in self.nerves:
            if hasattr(nerve, "stop"):
                try:
                    await nerve.stop()
                    logger.info(
                        boot_t("boot.log.nerve_stopped_graceful", name=nerve.__class__.__name__)
                    )
                except Exception as e:
                    logger.warning(_nrv_t("nrv.warn.nerve_stop", cls=nerve.__class__.__name__, e=e))

    def get_status(self) -> Dict[str, Any]:
        """供 HealthServer / BootManager 查询"""
        return {
            "total_nerves": len(self.nerves),
            "registered": [n.__class__.__name__ for n in self.nerves],
            "initialized": self._initialized,
        }


# ====================== 全局单例 ======================
nerve_registry = NerveRegistry()
# =====================================================
