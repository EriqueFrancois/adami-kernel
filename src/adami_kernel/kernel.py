"""AdamI Kernel process entrypoint.

This module wires together:
- logging bootstrap
- OpenTelemetry initialization (console / OTLP based on settings)
- component initialization and lifecycle management

The canonical executable entrypoint is the Poetry script `adami`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import asyncio
import logging
from logging.handlers import RotatingFileHandler

from rich.console import Console

from adami_kernel.config import settings
from adami_kernel.i18n.boot_msg import boot_t

# === 日志轮转（防止无限增长；路径与大小见 config.path_kernel_log_file 等）===
_log_path = settings.path_kernel_log_file
Path(_log_path).parent.mkdir(parents=True, exist_ok=True)
handler = RotatingFileHandler(
    _log_path,
    maxBytes=int(settings.ADAMI_KERNEL_LOG_MAX_BYTES),
    backupCount=int(settings.ADAMI_KERNEL_LOG_BACKUP_COUNT),
)
logging.basicConfig(
    handlers=[handler],
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    force=True,
)
for name in list(logging.root.manager.loggerDict):
    logger_obj = logging.getLogger(name)
    logger_obj.propagate = False
    for h in logger_obj.handlers[:]:
        if isinstance(h, logging.StreamHandler):
            logger_obj.removeHandler(h)
# ====================== Phase 4 OpenTelemetry 强制初始化 ======================
import os

from adami_kernel.core.boot_manager import BootManager
from adami_kernel.core.component_initializer import ComponentInitializer
from adami_kernel.core.lifecycle_manager import LifecycleManager

os.environ["OTEL_SERVICE_NAME"] = "adami-kernel"
os.environ["OTEL_TRACES_EXPORTER"] = "console"
os.environ["OTEL_METRICS_EXPORTER"] = "console"
os.environ["OTEL_LOGS_EXPORTER"] = "console"

from adami_kernel.web.otel import AdamIOtel

try:
    AdamIOtel.init()
except Exception as e:
    print(boot_t("boot.kernel_otel_failed", detail=str(e)))

print(boot_t("boot.env_loaded_stdout"))

logger = logging.getLogger("AdamI-Kernel")
console = Console()


class AdamiKernel:
    """AdamI 工业级微内核入口（精简版）
    仅保留公共 API 与生命周期控制，所有组件初始化已拆分到 core/ 模块
    """

    def __init__(self) -> None:
        logger.info("Initializing AdamI Kernel")
        self.initializer = ComponentInitializer()
        # 关键：传递 self 作为 kernel 参数，确保 market_routes 等组件能正确注入
        self.components = self.initializer.initialize_components(kernel=self)
        self.boot_manager = BootManager(self.components)
        self.lifecycle_manager = LifecycleManager(self.components)
        self._running = False
        logger.info(boot_t("boot.kernel_components_init_done"))

    async def boot(self) -> None:
        await self.boot_manager.boot()

    async def run_forever(self) -> None:
        await self.boot()
        await self.lifecycle_manager.run_forever()

    async def _event_consumer(self) -> None:
        await self.lifecycle_manager.event_consumer()


# ====================== Poetry 启动入口 ======================
def main() -> None:
    """Run the kernel until interrupted or fatal error."""
    try:
        # First-run initialization gate: refuse to boot until operator completes minimal setup.
        from adami_kernel.nexus.first_run_init import (
            needs_first_run_init,
            run_first_run_initializer,
            validate_startup_prereqs,
        )

        if needs_first_run_init():
            run_first_run_initializer(console)
            # Re-check after writing overrides. If still not complete, exit with non-zero.
            from adami_kernel.nexus.first_run_init import needs_first_run_init as _needs_again

            if _needs_again():
                print(boot_t("init.cli.required_exit"))
                raise SystemExit(2)
        else:
            missing = validate_startup_prereqs()
            if missing:
                print(boot_t("init.validate.failed_title"))
                for item in missing:
                    print(f"- {item.hint}")
                print(boot_t("init.validate.failed_footer"))
                raise SystemExit(2)

        asyncio.run(AdamiKernel().run_forever())
    except KeyboardInterrupt:
        logger.info(boot_t("boot.kernel_shutdown_ok"))
    except asyncio.CancelledError:
        logger.info(boot_t("boot.kernel_shutdown_cancelled"))
    except Exception as e:
        logger.critical(boot_t("boot.kernel_boot_failed", detail=str(e)), exc_info=True)


if __name__ == "__main__":
    main()
# 文件路径: src/adami_kernel/kernel.py (结束)
