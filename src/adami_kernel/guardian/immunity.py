# --- START OF FILE immunity.py ---

import asyncio
import logging

from adami_kernel.i18n.boot_msg import boot_t
from adami_kernel.observability.timeout_budget import BudgetExceededError, clamp_timeout_to_budget

logger = logging.getLogger("AdamI-Immunity")


class ImmunitySystem:
    """
    自身免疫系统 (Immunity System)
    负责资源级熔断、死循环检测与痛觉神经反馈。
    【工业级加固】：防御大模型生成的代码恶意吞没 CancelledError，杜绝僵尸协程。
    """

    @staticmethod
    async def run_with_timeout(coro, timeout: float = 45.0):
        # 显式创建 Task 以获取对其生命周期的绝对控制权
        task = asyncio.create_task(coro)
        try:
            eff = clamp_timeout_to_budget(float(timeout) if timeout is not None else None)
            if eff is None:
                return await task
            return await asyncio.wait_for(task, timeout=float(eff))

        except asyncio.TimeoutError:
            err_msg = boot_t("cjk_gate.immunity_timeout", timeout=int(timeout))
            logger.warning(err_msg)

            # 双重保险：如果 wait_for 未能杀掉（比如被恶意 except Exception 吞没），强制发起二次刺杀
            if not task.done():
                task.cancel()
                logger.error(boot_t("boot.log.immunity_force_detach"))

            raise TimeoutError(err_msg) from None
        except BudgetExceededError:
            # Treat as an immediate hard-stop: no remaining budget to safely run this coroutine.
            if not task.done():
                task.cancel()
            raise

        except asyncio.CancelledError:
            logger.debug(boot_t("boot.log.immunity_task_cancelled_external"))
            raise


# --- END OF FILE immunity.py ---
