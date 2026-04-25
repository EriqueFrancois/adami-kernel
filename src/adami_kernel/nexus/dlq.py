# --- START OF FILE dlq.py ---

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Dict, List

logger = logging.getLogger("AdamI-DLQ")

# ====================== 【核心修复】引入中央数据库助手 ======================
from adami_kernel.config import settings
from adami_kernel.hippocampus.db_helper import DatabaseHelper
from adami_kernel.i18n import t
from adami_kernel.i18n.boot_msg import boot_t

# =================================================================================


def _dlqx_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class DeadLetterQueue:
    """死信队列 (SQLite 持久化版)：防止事件因系统繁忙而永久丢失
    【Bug 3 核心修复】：支持 retry_count 自动递增 + 超过上限永久丢弃
    【本次强化】：init_db 自动 schema 迁移 + 事务原子性 + payload 容错解析
    【本次核心修复】：全面引入 async with cursor 游标上下文管理器，彻底杜绝 Cursor 泄漏。
    【本次核心修复】：JSON 序列化工业级硬化防御（default=str + 异常兜底）
    """

    def __init__(self, db_path=None):
        self.db_path = db_path if db_path is not None else settings.path_dlq_db
        self._lock = asyncio.Lock()
        self._conn = None

    # ====================== 【核心修复】获取持久化连接 ======================
    async def _get_conn(self):
        # 信任 DatabaseHelper 的全局连接池与探活机制，直接获取安全的长连接
        self._conn = await DatabaseHelper.get_aiosqlite_conn(self.db_path)
        return self._conn

    # =================================================================================

    async def init_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        # 强制 WAL 模式 + 异步初始化
        await DatabaseHelper.ensure_wal(self.db_path)
        await self._init_schema_async()

        logger.info(boot_t("boot.log.dlq_init"))

    async def _init_schema_async(self):
        conn = await self._get_conn()

        # ====================== 基础建表（游标安全版） ======================
        async with conn.cursor() as cursor:
            await cursor.execute("""CREATE TABLE IF NOT EXISTS dead_letters
                                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                                   trace_id TEXT,
                                   source_module TEXT,
                                   target_topic TEXT,
                                   priority INTEGER,
                                   payload TEXT,
                                   retry_count INTEGER DEFAULT 0,
                                   created_at TEXT,
                                   last_attempt TEXT)""")
        # =================================================================

        # ====================== 自动 Schema 迁移（游标安全版） ======================
        async with conn.execute("PRAGMA table_info(dead_letters)") as cursor:
            rows = await cursor.fetchall()
        existing_columns = {row[1] for row in rows}

        migration_map = {
            "trace_id": "TEXT",
            "source_module": "TEXT",
            "target_topic": "TEXT",
            "priority": "INTEGER",
            "payload": "TEXT",
            "retry_count": "INTEGER DEFAULT 0",
            "created_at": "TEXT",
            "last_attempt": "TEXT",
        }

        async with conn.cursor() as cursor:
            for col, col_type in migration_map.items():
                if col not in existing_columns:
                    try:
                        await cursor.execute(
                            f"ALTER TABLE dead_letters ADD COLUMN {col} {col_type}"
                        )
                        logger.info(_dlqx_t("dlqx.log.migration_col", col=col))
                    except Exception as e:
                        logger.warning(_dlqx_t("dlqx.warn.migration_col", col=col, e=e))

            await cursor.execute(
                """CREATE INDEX IF NOT EXISTS idx_dlq_trace ON dead_letters(trace_id)"""
            )
        await conn.commit()
        # =================================================================

    async def push(self, event_dict: dict):
        """推入死信队列（自动递增 retry_count + 工业级防序列化崩溃）"""
        async with self._lock:
            retry_count = event_dict.get("retry_count", 0) + 1
            now = datetime.now().isoformat()

            # ====================== JSON 序列化硬化防御 ======================
            try:
                safe_payload = json.dumps(
                    event_dict.get("payload", {}),
                    ensure_ascii=False,
                    default=str,  # 致命修复：遇到无法序列化的对象，强制转为字符串！
                )
            except Exception as e:
                logger.error(_dlqx_t("dlqx.err.serialize", e=e))
                safe_payload = json.dumps(
                    {
                        "dlq_error": "Unserializable payload",
                        "raw_repr": str(event_dict.get("payload")),
                        "original_error": str(e),
                    }
                )
            # =================================================================

            conn = await self._get_conn()
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """INSERT INTO dead_letters
                                      (trace_id, source_module, target_topic, priority, payload, retry_count, created_at, last_attempt)
                                      VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event_dict.get("trace_id", "unknown"),
                        event_dict.get("source_module", "unknown"),
                        event_dict.get("target_topic", "unknown"),
                        event_dict.get("priority", 0),
                        safe_payload,
                        retry_count,
                        now,
                        now,
                    ),
                )
            await conn.commit()

            tid = event_dict.get("trace_id", "unknown")
            if retry_count > 5:
                logger.warning(_dlqx_t("dlqx.warn.retry_cap", tid=tid, n=retry_count))
            else:
                logger.warning(_dlqx_t("dlqx.warn.enqueued", tid=tid, n=retry_count))

    async def pop_all(self) -> List[Dict]:
        """原子化取出所有死信 + payload 容错解析"""
        async with self._lock:
            conn = await self._get_conn()

            try:
                async with conn.cursor() as cursor:
                    await cursor.execute("BEGIN IMMEDIATE")

                async with conn.execute("SELECT * FROM dead_letters") as cursor:
                    rows = await cursor.fetchall()
                    if not rows:
                        await conn.commit()
                        return []
                    col_names = [col[0] for col in cursor.description]

                dead_letters = []
                ids_to_delete = []

                for row in rows:
                    ev_dict = dict(zip(col_names, row, strict=False))

                    # ====================== 关键容错：payload 可能是字符串 ======================
                    if isinstance(ev_dict.get("payload"), str):
                        try:
                            ev_dict["payload"] = json.loads(ev_dict["payload"])
                        except (json.JSONDecodeError, TypeError):
                            ev_dict["payload"] = {
                                "raw_payload": ev_dict["payload"],
                                "parse_error": True,
                            }
                    # =================================================================

                    dead_letters.append(ev_dict)
                    ids_to_delete.append(ev_dict["id"])

                # 原子删除（游标安全版）
                if ids_to_delete:
                    placeholders = ",".join("?" * len(ids_to_delete))
                    async with conn.cursor() as cursor:
                        await cursor.execute(
                            f"DELETE FROM dead_letters WHERE id IN ({placeholders})", ids_to_delete
                        )

                await conn.commit()
                return dead_letters
            except Exception:
                await conn.rollback()
                raise

    async def size(self) -> int:
        async with self._lock:
            conn = await self._get_conn()
            async with conn.execute("SELECT COUNT(*) FROM dead_letters") as cursor:
                row = await cursor.fetchone()
            return row[0] if row else 0

    async def clear(self):
        async with self._lock:
            conn = await self._get_conn()
            async with conn.cursor() as cursor:
                await cursor.execute("DELETE FROM dead_letters")
            await conn.commit()
            logger.info(_dlqx_t("dlqx.log.cleared"))


# --- END OF FILE dlq.py ---
