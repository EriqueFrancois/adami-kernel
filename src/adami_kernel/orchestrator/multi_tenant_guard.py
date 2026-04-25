# --- START OF FILE multi_tenant_guard.py ---
import asyncio
import logging
from typing import Dict, Optional

from adami_kernel.i18n.boot_msg import boot_t

logger = logging.getLogger("AdamI-MultiTenantGuard")


class MultiTenantGuard:
    """
    AdamI 2.0 多租户与并发安全守卫
    - 强制所有 LayeredMemory 操作带 chat_id
    - 使用 per-workflow asyncio.Lock 防止脏写
    """

    def __init__(self):
        self.session_locks: Dict[str, asyncio.Lock] = {}
        logger.info(boot_t("boot.log.multi_tenant_guard_init"))

    async def validate_chat_id(self, chat_id: Optional[str]):
        """强制校验 chat_id（所有工作流操作必须携带）"""
        if not chat_id or not isinstance(chat_id, (str, int)):
            raise ValueError(boot_t("cjk_gate.tenant_chat_id_required"))
        logger.debug(boot_t("boot.log.multi_tenant_chat_validated", chat_id=chat_id))

    async def acquire_lock(self, workflow_id: str, chat_id: str) -> asyncio.Lock:
        """获取 workflow 级锁（防止并发脏写）"""
        key = f"{chat_id}:{workflow_id}"
        if key not in self.session_locks:
            self.session_locks[key] = asyncio.Lock()
        lock = self.session_locks[key]
        await lock.acquire()
        logger.debug(boot_t("boot.log.multi_tenant_lock_acquired", lock_key=key))
        return lock

    def release_lock(self, workflow_id: str, chat_id: str):
        """释放 workflow 级锁"""
        key = f"{chat_id}:{workflow_id}"
        if key in self.session_locks:
            self.session_locks[key].release()
            logger.debug(boot_t("boot.log.multi_tenant_lock_released", lock_key=key))


# ====================== 全局单例 ======================
multi_tenant_guard = MultiTenantGuard()
# =================================================================================

# --- END OF FILE multi_tenant_guard.py ---
