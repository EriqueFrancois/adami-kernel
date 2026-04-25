import asyncio
import logging
import time
from typing import Dict, Generic, List, Optional, Tuple, TypeVar

from adami_kernel.config import settings
from adami_kernel.i18n import t

T = TypeVar("T")

logger = logging.getLogger("AdamI-AsyncLRUCache")


def _hpcache_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class AsyncLRUCache(Generic[T]):
    """
    异步 LRU 内存缓存（工业级）。
    支持泛型、TTL 过期机制以及按域 (Domain) 精准清理。
    【Bug 修复】新增 cleanup_expired 方法，彻底解决 LayeredMemory 调用崩溃。
    """

    def __init__(self, maxsize: int = 1000, ttl: float = 300.0) -> None:
        self.maxsize = maxsize
        self.ttl = ttl
        self._cache: Dict[str, Tuple[float, T]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[T]:
        """获取缓存，若过期则自动清理"""
        async with self._lock:
            if key in self._cache:
                timestamp, value = self._cache[key]
                if time.time() - timestamp <= self.ttl:
                    # LRU 提升：移到最新位置
                    self._cache.pop(key)
                    self._cache[key] = (timestamp, value)
                    return value
                else:
                    self._cache.pop(key)
            return None

    async def put(self, key: str, value: T) -> None:
        """存入缓存，若达到容量上限则淘汰最老的元素"""
        async with self._lock:
            if key in self._cache:
                self._cache.pop(key)
            elif len(self._cache) >= self.maxsize:
                # 弹出第一个插入的元素（最老）
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = (time.time(), value)

    async def clear_domain(self, domain: str) -> None:
        """
        精准缓存失效：清空特定域下的所有键值对。
        用于 Write-Through 策略时保持 L1/L2 数据一致性。
        """
        async with self._lock:
            target_prefix = f"mem_ref_{domain}"
            keys_to_remove: List[str] = [
                k for k in self._cache.keys() if k.startswith(target_prefix)
            ]
            for k in keys_to_remove:
                self._cache.pop(k, None)

    # ====================== 【核心修复】TTL 过期清理 ======================
    async def cleanup_expired(self) -> int:
        """
        工业级过期项清理接口。
        返回实际清理数量（供 LayeredMemory 日志统计）。
        已在 _periodic_cache_cleanup 与 shutdown 中调用。
        """
        async with self._lock:
            now = time.time()
            # 一次性收集所有过期键（避免迭代中修改字典）
            expired_keys = [k for k, (ts, _) in self._cache.items() if now - ts > self.ttl]
            # 原子删除
            for k in expired_keys:
                self._cache.pop(k, None)

            cleaned = len(expired_keys)
            if cleaned > 0:
                logger.info(_hpcache_t("hpcache.log.cleaned", n=cleaned))
            return cleaned

    # =====================================================================
