# --- START OF FILE db_helper.py ---

import asyncio
import logging
from typing import Dict

import aiosqlite

from adami_kernel.config import settings
from adami_kernel.i18n import t
from adami_kernel.i18n.boot_msg import boot_t

logger = logging.getLogger("AdamI-DBHelper")


def _dbhp_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class DatabaseHelper:
    """
    AdamI 中央数据库连接工厂（工业级重构版）
    - 细粒度锁：按 db_path 分配锁，消除全局锁导致的并发性能瓶颈。
    - 强制 WAL 模式 + busy_timeout + 缓存优化，杜绝 database is locked。
    - 自动连接保活与重建，支持优雅关闭。
    【本次核心修复】：彻底解决 aiosqlite.Connection 缺乏 _closed 属性导致每次请求不断创建新连接的严重 File Descriptor (FD) 泄漏问题。
    """

    _connections: Dict[str, aiosqlite.Connection] = {}
    _locks: Dict[str, asyncio.Lock] = {}
    _global_lock = asyncio.Lock()  # 用于安全地创建细粒度锁

    @classmethod
    async def _get_lock_for_db(cls, db_path: str) -> asyncio.Lock:
        """获取特定数据库的专属锁（双重检查锁定模式）"""
        if db_path not in cls._locks:
            async with cls._global_lock:
                if db_path not in cls._locks:
                    cls._locks[db_path] = asyncio.Lock()
        return cls._locks[db_path]

    @classmethod
    async def get_aiosqlite_conn(
        cls, db_path: str, timeout: float = 8.0, use_cache: bool = True
    ) -> aiosqlite.Connection:
        """
        获取（或复用）持久化连接
        :param use_cache: 如果为 False，则每次创建新连接，不缓存（用于调试）
        """
        db_lock = await cls._get_lock_for_db(db_path)

        async with db_lock:
            # 如果不使用缓存，直接创建新连接
            if not use_cache:
                try:
                    conn = await cls._create_new_connection(db_path, timeout)
                    return conn
                except Exception as e:
                    logger.error(_dbhp_t("dbhp.err.create_conn", path=db_path, e=e))
                    raise

            # 使用缓存
            # 【核心修复】直接尝试使用现有连接进行 Ping 测试，不再依赖不可靠的 _closed 属性
            if db_path in cls._connections:
                conn = cls._connections[db_path]
                try:
                    # 使用 async with 确保游标安全释放，避免 Cursor 泄漏
                    async with conn.execute("SELECT 1") as cursor:
                        await cursor.fetchone()
                    return conn
                except Exception as e:
                    logger.warning(_dbhp_t("dbhp.warn.conn_stale", path=db_path, e=e))
                    try:
                        await conn.close()
                    except Exception as close_err:
                        logger.debug(_dbhp_t("dbhp.debug.close_ignore", e=close_err))
                    cls._connections.pop(db_path, None)

            # 2. 如果连接不存在或已失效，创建新连接并缓存
            try:
                conn = await cls._create_new_connection(db_path, timeout)
                cls._connections[db_path] = conn
                return conn
            except Exception as e:
                logger.error(_dbhp_t("dbhp.err.create_conn", path=db_path, e=e))
                raise

    @classmethod
    async def _create_new_connection(cls, db_path: str, timeout: float) -> aiosqlite.Connection:
        """创建新连接并配置 PRAGMA"""
        conn = await aiosqlite.connect(db_path, timeout=timeout)

        # 强制 WAL 模式
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute("PRAGMA synchronous=NORMAL;")
        await conn.execute("PRAGMA busy_timeout=8000;")
        await conn.execute("PRAGMA cache_size=-128000;")
        await conn.execute("PRAGMA foreign_keys=ON;")
        await conn.commit()

        logger.debug(_dbhp_t("dbhp.debug.conn_ready", path=db_path))
        return conn

    @classmethod
    async def ensure_wal(cls, db_path: str) -> None:
        """项目启动时强制确保 WAL 模式（幂等）"""
        await cls.get_aiosqlite_conn(db_path)  # 复用或重建
        logger.info(boot_t("boot.log.db_wal_enabled", path=db_path))

    @classmethod
    async def close_all(cls) -> None:
        """优雅关闭所有缓存连接（供 kernel shutdown 使用）"""
        async with cls._global_lock:
            for db_path, conn in list(cls._connections.items()):
                db_lock = cls._locks.get(db_path)
                if db_lock:
                    async with db_lock:
                        try:
                            # aiosqlite 建议直接调用 close()
                            await conn.close()
                            logger.info(_dbhp_t("dbhp.log.closed", path=db_path))
                        except Exception as e:
                            logger.warning(_dbhp_t("dbhp.warn.close_fail", path=db_path, e=e))
            cls._connections.clear()
            cls._locks.clear()


# --- END OF FILE db_helper.py ---
