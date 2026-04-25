# src/adami_kernel/hippocampus/layered_memory.py
# --- START OF FILE layered_memory.py ---

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiosqlite

# =================================================================================
from adami_kernel.hippocampus.cache import AsyncLRUCache
from adami_kernel.hippocampus.episodic_memory import EpisodicMemory
from adami_kernel.i18n import t as i18n_t
from adami_kernel.i18n.boot_msg import boot_t

# ====================== 【2.0 新增】WorkflowState / TDD / Reflexion 支持 ======================
from adami_kernel.orchestrator.workflow_models import WorkflowState


def _laym_t(key: str, **kwargs) -> str:
    return i18n_t(key, locale=settings.effective_ui_default_locale(), **kwargs)


# === ChromaDB 支持 ===
try:
    import chromadb

    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False

from adami_kernel.config import settings
from adami_kernel.hippocampus.db_helper import DatabaseHelper
from adami_kernel.orchestrator.long_task_checkpoint import (
    CheckpointSaveResult,
    phase_checkpoint_domain,
    unwrap_phase_payload,
    workflow_checkpoint_meta_domain,
    wrap_phase_envelope,
)

logger = logging.getLogger("AdamI-LayeredMemory")


def _json_default(obj: Any):
    """json.dumps 默认编码器：优先使用 isoformat，其次退化为 str。"""
    try:
        if isinstance(obj, datetime):
            return obj.isoformat()
        iso = getattr(obj, "isoformat", None)
        if callable(iso):
            return iso()
    except Exception:
        pass
    return str(obj)


class LayeredMemory:
    """
    AdamI 分层记忆系统 V2.8 (工业级终极并发安全版)
    【本次核心修复 1】：移除 use_cache=False，复用长连接。
    【本次核心修复 2】：引入 asyncio.Lock (_db_lock)，确保单连接并发安全。
    【本次核心修复 3】：全面应用 `async with conn.cursor()` 上下文管理器，彻底阻断游标 (Cursor) 积累导致的文件/内存泄漏。
    【本次新增】深度洗髓日志降级为 DEBUG + 防抖（仅写入>0时记录），解决每5分钟刷屏问题。
    【Step 3 新增】Checkpointing 机制；模块四步骤 2：统一命名空间 checkpoint/v1/wf/{id}/ph/{phase} + last_good 指针
    【本次修复】：_periodic_cache_cleanup 方法开头显式获取 logger，彻底解决“name 'logger' is not defined”异常（防止局部变量覆盖或作用域问题）。
    """

    def __init__(self):
        self.short_term = AsyncLRUCache(maxsize=800, ttl=3600)
        self.mid_term = EpisodicMemory()
        self.db_path = settings.path_l2_memory_db
        self.importance_scores: Dict[str, float] = {}
        self.memory_aliases: Dict[str, str] = {}

        # ChromaDB 向量索引
        self.chroma_client = None
        self.collections = {}

        # 缓存清理后台任务句柄
        self._cleanup_task: Optional[asyncio.Task] = None

        # 域名统计缓存 (30秒TTL)
        self.domain_stats_cache = AsyncLRUCache(maxsize=100, ttl=30)

        # ====================== 【核心修复】单连接并发安全锁 ======================
        self._db_lock = asyncio.Lock()
        # =====================================================================

        self._cleanup_importance_scores()

        logger.debug(
            _laym_t("laym.debug.init", chroma="yes" if CHROMA_AVAILABLE else "no"),
        )

    def _cleanup_importance_scores(self):
        bad_keys = []
        for k, v in list(self.importance_scores.items()):
            try:
                self.importance_scores[k] = float(v)
            except Exception:
                bad_keys.append(k)
        for k in bad_keys:
            self.importance_scores.pop(k, None)

    async def _get_conn(self) -> aiosqlite.Connection:
        """带重试的连接获取，确保数据库文件可访问"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        if not os.path.exists(self.db_path):
            try:
                open(self.db_path, "a").close()
                logger.info(_laym_t("laym.log.db_created", path=self.db_path))
            except Exception as e:
                logger.error(
                    _laym_t("laym.err.db_create", path=self.db_path, e=e),
                )
                raise

        for attempt in range(3):
            try:
                return await DatabaseHelper.get_aiosqlite_conn(self.db_path)
            except Exception as e:
                logger.warning(_laym_t("laym.warn.db_conn", attempt=attempt + 1, e=e))
                if attempt == 2:
                    raise
                await asyncio.sleep(1)

    async def initialize(self, start_periodic_cleanup: bool = True):
        await DatabaseHelper.ensure_wal(self.db_path)
        await self._init_user_table_async()
        await self._recover_user_memories()
        await self._init_chroma()

        if start_periodic_cleanup and (self._cleanup_task is None or self._cleanup_task.done()):
            self._cleanup_task = asyncio.create_task(self._periodic_cache_cleanup())
            logger.debug(_laym_t("laym.debug.cache_task"))

        logger.info(_laym_t("laym.log.ready"))

    async def _periodic_cache_cleanup(self):
        import logging

        logger = logging.getLogger("AdamI-LayeredMemory")
        while True:
            try:
                await asyncio.sleep(300)
                cleaned = await self.short_term.cleanup_expired()
                if cleaned > 0:
                    logger.info(_laym_t("laym.log.cache_cleaned", n=cleaned))
            except asyncio.CancelledError:
                logger.info(_laym_t("laym.log.cache_abort"))
                break
            except Exception as e:
                logger.warning(_laym_t("laym.warn.cache_exc", e=e))
                await asyncio.sleep(10)

    async def cleanup_cache(self):
        cleaned = await self.short_term.cleanup_expired()
        logger.info(_laym_t("laym.log.cache_manual", n=cleaned))

    async def _init_user_table_async(self):
        async with self._db_lock:
            conn = await self._get_conn()
            async with conn.cursor() as cursor:
                await cursor.execute("""CREATE TABLE IF NOT EXISTS user_memories
                                      (key TEXT PRIMARY KEY, value TEXT, importance REAL, timestamp TEXT)""")
                await cursor.execute("""CREATE TABLE IF NOT EXISTS memories
                                      (id INTEGER PRIMARY KEY AUTOINCREMENT,
                                       trace_id TEXT, domain TEXT,
                                       payload TEXT, timestamp DATETIME)""")
                await cursor.execute(
                    """CREATE INDEX IF NOT EXISTS idx_memories_domain ON memories(domain)"""
                )
                await cursor.execute(
                    """CREATE INDEX IF NOT EXISTS idx_memories_timestamp ON memories(timestamp)"""
                )
                await cursor.execute(
                    """CREATE INDEX IF NOT EXISTS idx_memories_domain_id ON memories(domain, id)"""
                )
            await conn.commit()
            logger.debug(_laym_t("laym.debug.schema_ok"))

    async def _recover_user_memories(self):
        pass

    async def _init_chroma(self):
        if not CHROMA_AVAILABLE:
            logger.warning(_laym_t("laym.warn.chroma_missing"))
            return
        try:
            self.chroma_client = chromadb.PersistentClient(path=settings.path_chroma_persist_dir)
            for domain in ["code_ops", "semantic_rules"]:
                self.collections[domain] = self.chroma_client.get_or_create_collection(name=domain)
            logger.debug(_laym_t("laym.debug.chroma_ok"))
        except Exception as e:
            logger.warning(_laym_t("laym.warn.chroma_init", e=e))

    # ====================== Checkpointing：模块四统一命名空间 + 乐观锁 seq ======================

    async def get_workflow_phase_checkpoint_record(
        self, workflow_id: str, phase: str
    ) -> Optional[Dict[str, Any]]:
        """返回某 workflow × phase 的最新信封（含 seq、payload）；无则 None。"""
        domain = phase_checkpoint_domain(workflow_id, phase)
        try:
            async with self._db_lock:
                conn = await self._get_conn()
                async with conn.execute(
                    "SELECT payload FROM memories WHERE domain = ? ORDER BY id DESC LIMIT 1",
                    (domain,),
                ) as cursor:
                    row = await cursor.fetchone()
            if not row or not row[0]:
                return None
            return json.loads(row[0])
        except Exception as e:
            logger.error(
                _laym_t("laym.err.ckpt_read", wid=workflow_id, phase=phase, e=e),
            )
            return None

    async def save_workflow_phase_checkpoint(
        self,
        workflow_id: str,
        phase: str,
        payload_body: Dict[str, Any],
        *,
        workflow_state_version: Optional[int] = None,
        expected_seq: Optional[int] = None,
        update_last_good: bool = True,
    ) -> CheckpointSaveResult:
        """
        写入 checkpoint/v1/wf/{workflow_id}/ph/{phase} 的新版本。
        expected_seq 非空时：要求当前库内最新 seq 与之相等，否则返回 conflict（乐观锁）。
        expected_seq 为空：在锁内读取最新 seq 并追加 +1，无跨调用冲突检测。
        """
        domain = phase_checkpoint_domain(workflow_id, phase)
        try:
            async with self._db_lock:
                conn = await self._get_conn()
                async with conn.execute(
                    "SELECT payload FROM memories WHERE domain = ? ORDER BY id DESC LIMIT 1",
                    (domain,),
                ) as cursor:
                    row = await cursor.fetchone()
                latest_seq = 0
                if row and row[0]:
                    try:
                        env = json.loads(row[0])
                        latest_seq = int(env.get("seq", 0))
                    except Exception:
                        latest_seq = 0
                if expected_seq is not None and latest_seq != expected_seq:
                    logger.warning(
                        _laym_t(
                            "laym.warn.ckpt_lock",
                            wid=workflow_id,
                            phase=phase,
                            exp=expected_seq,
                            actual=latest_seq,
                        ),
                    )
                    return CheckpointSaveResult(ok=False, seq=latest_seq, conflict=True)
                new_seq = latest_seq + 1
                envelope = wrap_phase_envelope(
                    seq=new_seq,
                    phase=phase,
                    payload=payload_body,
                    workflow_state_version=workflow_state_version,
                )
                payload_str = json.dumps(envelope, ensure_ascii=False, default=_json_default)
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "INSERT INTO memories (trace_id, domain, payload, timestamp) VALUES (?, ?, ?, ?)",
                        (str(new_seq), domain, payload_str, datetime.now()),
                    )
                if update_last_good:
                    meta_domain = workflow_checkpoint_meta_domain(workflow_id)
                    pointer = {
                        "phase": phase,
                        "seq": new_seq,
                        "workflow_state_version": workflow_state_version,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                    meta_str = json.dumps(pointer, ensure_ascii=False, default=_json_default)
                    async with conn.cursor() as cursor:
                        await cursor.execute(
                            "INSERT INTO memories (trace_id, domain, payload, timestamp) VALUES (?, ?, ?, ?)",
                            ("last_good", meta_domain, meta_str, datetime.now()),
                        )
                await conn.commit()
            await self.short_term.put(f"checkpoint_ref_{workflow_id}_{phase}", payload_body)
            logger.info(
                _laym_t(
                    "laym.log.ckpt_saved",
                    wid=workflow_id,
                    phase=phase,
                    seq=new_seq,
                ),
            )
            return CheckpointSaveResult(ok=True, seq=new_seq, conflict=False)
        except Exception as e:
            logger.error(
                _laym_t("laym.err.ckpt_save", wid=workflow_id, phase=phase, e=e),
            )
            return CheckpointSaveResult(ok=False, seq=0, conflict=False)

    async def get_last_good_checkpoint(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """读取最近成功阶段写入的 last_good 指针（phase + seq + workflow_state_version）。"""
        meta_domain = workflow_checkpoint_meta_domain(workflow_id)
        try:
            async with self._db_lock:
                conn = await self._get_conn()
                async with conn.execute(
                    "SELECT payload FROM memories WHERE domain = ? AND trace_id = ? ORDER BY id DESC LIMIT 1",
                    (meta_domain, "last_good"),
                ) as cursor:
                    row = await cursor.fetchone()
            if not row or not row[0]:
                return None
            return json.loads(row[0])
        except Exception as e:
            logger.error(
                _laym_t("laym.err.last_good_read", wid=workflow_id, e=e),
            )
            return None

    async def record_checkpoint_failure(
        self,
        workflow_id: str,
        *,
        failed_phase: str,
        message: str = "",
        workflow_state_version: Optional[int] = None,
    ) -> None:
        """阶段失败元数据：不推进 last_good，仅记录 last_failure 供恢复/审计。"""
        meta_domain = workflow_checkpoint_meta_domain(workflow_id)
        body = {
            "failed_phase": failed_phase,
            "message": (message or "")[:2000],
            "workflow_state_version": workflow_state_version,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            async with self._db_lock:
                conn = await self._get_conn()
                payload_str = json.dumps(body, ensure_ascii=False, default=_json_default)
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "INSERT INTO memories (trace_id, domain, payload, timestamp) VALUES (?, ?, ?, ?)",
                        ("last_failure", meta_domain, payload_str, datetime.now()),
                    )
                await conn.commit()
            logger.info(
                _laym_t("laym.log.last_fail", wid=workflow_id, phase=failed_phase),
            )
        except Exception as e:
            logger.error(
                _laym_t("laym.err.last_fail_write", wid=workflow_id, e=e),
            )

    async def get_latest_checkpoint_failure(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        meta_domain = workflow_checkpoint_meta_domain(workflow_id)
        try:
            async with self._db_lock:
                conn = await self._get_conn()
                async with conn.execute(
                    "SELECT payload FROM memories WHERE domain = ? AND trace_id = ? ORDER BY id DESC LIMIT 1",
                    (meta_domain, "last_failure"),
                ) as cursor:
                    row = await cursor.fetchone()
            if not row or not row[0]:
                return None
            return json.loads(row[0])
        except Exception as e:
            logger.error(
                _laym_t("laym.err.last_fail_read", wid=workflow_id, e=e),
            )
            return None

    async def save_workflow_checkpoint(
        self, workflow_id: str, data: Dict[str, Any], domain: str = "researcher"
    ) -> None:
        """兼容入口：phase 名沿用原 domain 参数（如 researcher），并更新 last_good。"""
        await self.save_workflow_phase_checkpoint(
            workflow_id,
            domain,
            data,
            workflow_state_version=None,
            expected_seq=None,
            update_last_good=True,
        )

    async def get_workflow_checkpoint(
        self, workflow_id: str, domain: str = "researcher"
    ) -> Optional[Dict[str, Any]]:
        """读取最新业务负载：优先新命名空间，回退 legacy checkpoint_{domain}。"""
        try:
            rec = await self.get_workflow_phase_checkpoint_record(workflow_id, domain)
            if rec:
                body = unwrap_phase_payload(rec)
                if isinstance(body, dict) and body:
                    logger.info(
                        _laym_t("laym.log.ckpt_hit", wid=workflow_id, phase=domain),
                    )
                    return body
            legacy_domain = f"checkpoint_{domain}"
            async with self._db_lock:
                conn = await self._get_conn()
                async with conn.execute(
                    "SELECT payload FROM memories WHERE domain = ? AND trace_id = ? ORDER BY id DESC LIMIT 1",
                    (legacy_domain, workflow_id),
                ) as cursor:
                    row = await cursor.fetchone()
            if not row or not row[0]:
                return None
            payload = json.loads(row[0])
            logger.info(
                _laym_t("laym.log.ckpt_legacy", wid=workflow_id, domain=domain),
            )
            return payload
        except Exception as e:
            logger.error(
                _laym_t("laym.err.ckpt_compat", wid=workflow_id, e=e),
            )
            return None

    # =================================================================================

    async def store_experience(self, trace_id, domain, payload, chat_id: str = None):
        if chat_id:
            domain = f"{domain}_{chat_id}"

        try:
            async with self._db_lock:
                conn = await self._get_conn()
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "INSERT INTO memories (trace_id, domain, payload, timestamp) VALUES (?, ?, ?, ?)",
                        (
                            trace_id,
                            domain,
                            json.dumps(payload, ensure_ascii=False, default=_json_default),
                            datetime.now(),
                        ),
                    )
                await conn.commit()
            await self.short_term.put(f"mem_ref_{domain}_{trace_id}", payload)
            await self.domain_stats_cache.clear_domain("list_all_user_memories")
            if str(trace_id).startswith("skill_metadata_init"):
                logger.debug(
                    "[LayeredMemory] store_experience domain=%s trace=%s",
                    domain,
                    trace_id,
                )
            else:
                logger.info(
                    boot_t("boot.log.layered_memory_store", domain=domain, trace_id=trace_id)
                )
        except Exception as e:
            logger.error(_laym_t("laym.err.store_exp", domain=domain, tid=trace_id, e=e))

    async def save_workflow_state(self, state: WorkflowState) -> None:
        """原子保存工作流完整状态（强制 chat_id 隔离 + model_dump_json 自动处理 datetime）"""
        domain = f"workflow_state_{state.chat_id}"
        payload_str = state.model_dump_json()

        try:
            async with self._db_lock:
                conn = await self._get_conn()
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "INSERT INTO memories (trace_id, domain, payload, timestamp) VALUES (?, ?, ?, ?)",
                        (state.workflow_id, domain, payload_str, datetime.now()),
                    )
                await conn.commit()
            await self.short_term.put(f"wf_ref_{state.workflow_id}", state.model_dump(mode="json"))
            await self.domain_stats_cache.clear_domain("list_all_user_memories")
            logger.info(
                _laym_t(
                    "laym.log.wf_saved",
                    wid=state.workflow_id,
                    st=state.status,
                    chat=state.chat_id,
                )
            )
        except Exception as e:
            logger.error(_laym_t("laym.err.wf_save", wid=state.workflow_id, e=e))

    async def get_workflow_state(self, workflow_id: str, chat_id: str) -> Optional[WorkflowState]:
        """精确读取最新工作流状态（强制 chat_id 隔离）"""
        domain = f"workflow_state_{chat_id}"

        try:
            async with self._db_lock:
                conn = await self._get_conn()
                async with conn.execute(
                    "SELECT payload FROM memories WHERE domain = ? AND trace_id = ? ORDER BY id DESC LIMIT 1",
                    (domain, workflow_id),
                ) as cursor:
                    row = await cursor.fetchone()

            if not row or not row[0]:
                return None

            payload = json.loads(row[0])
            return WorkflowState.model_validate(payload)
        except Exception as e:
            logger.error(_laym_t("laym.err.wf_read", wid=workflow_id, e=e))
            return None

    async def get_workflow_state_by_workflow_id(self, workflow_id: str) -> Optional[WorkflowState]:
        """仅知 workflow_id 时读取最新一条（跨 workflow_state_* 域）。供 HITL resume/pause 等无 chat_id 的入口。"""
        try:
            async with self._db_lock:
                conn = await self._get_conn()
                async with conn.execute(
                    """
                    SELECT payload FROM memories
                    WHERE trace_id = ? AND domain LIKE 'workflow_state_%'
                    ORDER BY id DESC LIMIT 1
                    """,
                    (workflow_id,),
                ) as cursor:
                    row = await cursor.fetchone()
            if not row or not row[0]:
                return None
            return WorkflowState.model_validate(json.loads(row[0]))
        except Exception as e:
            logger.error(
                _laym_t("laym.err.wf_by_wid", wid=workflow_id, e=e),
            )
            return None

    async def list_active_workflows(
        self, chat_id: str = None, status: str = "RUNNING"
    ) -> List[WorkflowState]:
        """列出活跃工作流。

        - 当提供 chat_id 时：只返回该 chat_id 的工作流（domain=workflow_state_{chat_id}）。
        - 当 chat_id 为空时：聚合所有 workflow_state_* 域的最新状态并筛选 status。
        """
        domain = f"workflow_state_{chat_id}" if chat_id else "workflow_state"

        try:
            async with self._db_lock:
                conn = await self._get_conn()
                if chat_id:
                    async with conn.execute(
                        "SELECT payload FROM memories WHERE domain = ? ORDER BY id DESC",
                        (domain,),
                    ) as cursor:
                        rows = await cursor.fetchall()
                else:
                    # 聚合所有 chat 的 workflow_state_* 域（Web Dashboard 需要全局视角）
                    async with conn.execute(
                        "SELECT trace_id, payload FROM memories WHERE domain LIKE ? ORDER BY id DESC LIMIT 2000",
                        ("workflow_state_%",),
                    ) as cursor:
                        rows = await cursor.fetchall()

            latest_by_workflow: Dict[str, WorkflowState] = {}
            for row in rows:
                # rows may be (payload,) or (trace_id, payload)
                payload_str = row[-1]
                if not payload_str:
                    continue
                try:
                    payload = json.loads(payload_str)
                except Exception:
                    continue

                wf_id = payload.get("workflow_id") or (row[0] if len(row) == 2 else None)
                if not wf_id or wf_id in latest_by_workflow:
                    continue
                if payload.get("status") != status:
                    continue
                try:
                    latest_by_workflow[wf_id] = WorkflowState.model_validate(payload)
                except Exception:
                    continue

            return list(latest_by_workflow.values())
        except Exception as e:
            logger.error(_laym_t("laym.err.list_active", e=e))
            return []

    async def save_tdd_score(
        self, skill_name: str, score: float, report: Dict[str, Any], chat_id: str = None
    ):
        # store_experience 会在 chat_id 存在时自动 domain_suffix，避免这里手动拼接导致双后缀
        domain = "tdd_scores"
        payload = {
            "skill_name": skill_name,
            "score": score,
            "report": report,
            "timestamp": datetime.now().isoformat(),
        }
        await self.store_experience(
            f"tdd_{skill_name}_{int(time.time())}", domain, payload, chat_id
        )

    async def get_tdd_scores(self, limit: int = 20, chat_id: str = None) -> List[Dict]:
        # 兼容两种读法：
        # - chat_id 指定：读取该 chat 的 tdd_scores_{chat_id}
        # - chat_id 为空：优先读取全局 tdd_scores；若为空则回退读取 system 域（tdd_scores_system）
        domain = "tdd_scores"
        if chat_id:
            return await self.retrieve_recent(domain, limit=limit, chat_id=chat_id)
        out = await self.retrieve_recent(domain, limit=limit)
        if out:
            return out
        return await self.retrieve_recent(domain, limit=limit, chat_id="system")

    async def save_reflexion_log(
        self,
        workflow_id: str,
        root_cause: str,
        suggested_action: str,
        confidence: float,
        chat_id: str = None,
    ):
        # store_experience 会在 chat_id 存在时自动 domain_suffix，避免这里手动拼接导致双后缀
        domain = "reflexion_logs"
        payload = {
            "workflow_id": workflow_id,
            "root_cause": root_cause,
            "suggested_action": suggested_action,
            "confidence": confidence,
            "timestamp": datetime.now().isoformat(),
        }
        await self.store_experience(
            f"reflex_{workflow_id}_{int(time.time())}", domain, payload, chat_id
        )

    async def get_reflexion_logs(self, limit: int = 20, chat_id: str = None) -> List[Dict]:
        # 兼容两种读法：
        # - chat_id 指定：读取该 chat 的 reflexion_logs_{chat_id}
        # - chat_id 为空：优先读取全局 reflexion_logs；若为空则回退读取 system 域（reflexion_logs_system）
        domain = "reflexion_logs"
        if chat_id:
            return await self.retrieve_recent(domain, limit=limit, chat_id=chat_id)
        out = await self.retrieve_recent(domain, limit=limit)
        if out:
            return out
        return await self.retrieve_recent(domain, limit=limit, chat_id="system")

    async def semantic_search(self, query: str, domain: str = "code_ops", top_k: int = 3) -> list:
        if self.chroma_client and domain in self.collections:
            collection = self.collections[domain]
            try:
                results = await asyncio.to_thread(
                    collection.query, query_texts=[query], n_results=top_k, include=["documents"]
                )
                if results.get("documents") and results["documents"][0]:
                    return [json.loads(doc) for doc in results["documents"][0]]
            except Exception as e:
                logger.warning(_laym_t("laym.warn.chroma_q", e=e))

        all_mem = await self.retrieve_recent(domain, limit=50)
        query_words = set(query.lower().split())
        scored = [
            (len(query_words & set(json.dumps(mem, ensure_ascii=False).lower().split())), mem)
            for mem in all_mem
        ]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [mem for _, mem in scored[:top_k]]

    async def prune_domain(self, domain, keep_latest=0, chat_id: str = None):
        if chat_id:
            domain = f"{domain}_{chat_id}"
        try:
            async with self._db_lock:
                conn = await self._get_conn()
                async with conn.cursor() as cursor:
                    if keep_latest <= 0:
                        await cursor.execute("DELETE FROM memories WHERE domain = ?", (domain,))
                    else:
                        await cursor.execute(
                            """DELETE FROM memories WHERE domain = ? AND id NOT IN (
                                                SELECT id FROM memories WHERE domain = ? ORDER BY id DESC LIMIT ?
                                             )""",
                            (domain, domain, keep_latest),
                        )
                await conn.commit()
            await self.domain_stats_cache.clear_domain("list_all_user_memories")
            logger.info(_laym_t("laym.log.prune", domain=domain, keep=keep_latest))
        except Exception as e:
            logger.error(_laym_t("laym.err.prune", domain=domain, e=e))

    async def clear_and_rewrite_domain(self, domain: str, new_payloads: list, chat_id: str = None):
        if chat_id:
            domain = f"{domain}_{chat_id}"
        try:
            async with self._db_lock:
                conn = await self._get_conn()
                try:
                    async with conn.cursor() as cursor:
                        await cursor.execute("DELETE FROM memories WHERE domain = ?", (domain,))
                        if new_payloads:
                            records = [
                                (
                                    f"axiom_{int(datetime.now().timestamp())}_{i}",
                                    domain,
                                    json.dumps(p, ensure_ascii=False),
                                    datetime.now(),
                                )
                                for i, p in enumerate(new_payloads)
                            ]
                            await cursor.executemany(
                                "INSERT INTO memories (trace_id, domain, payload, timestamp) VALUES (?, ?, ?, ?)",
                                records,
                            )
                    await conn.commit()
                except Exception:
                    await conn.rollback()
                    raise
            await self.domain_stats_cache.clear_domain("list_all_user_memories")

            if len(new_payloads) > 0:
                logger.debug(
                    _laym_t(
                        "laym.debug.rewrite",
                        domain=domain,
                        n=len(new_payloads),
                    )
                )
        except Exception as e:
            logger.error(_laym_t("laym.err.rewrite", domain=domain, e=e))

    async def retrieve_recent(self, domain, limit=10, chat_id: str = None):
        if chat_id:
            domain = f"{domain}_{chat_id}"
        try:
            async with self._db_lock:
                conn = await self._get_conn()
                async with conn.execute(
                    "SELECT payload FROM memories WHERE domain = ? ORDER BY id DESC LIMIT ?",
                    (domain, limit),
                ) as cursor:
                    rows = await cursor.fetchall()
            return [json.loads(row[0]) for row in rows][::-1]
        except Exception as e:
            logger.error(_laym_t("laym.err.retrieve", domain=domain, e=e))
            return []

    async def list_all_user_memories(self) -> List[Dict[str, Any]]:
        cache_key = "list_all_user_memories"
        cached = await self.domain_stats_cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            async with self._db_lock:
                conn = await self._get_conn()
                # last payload per domain (by id) + count + last_updated
                async with conn.execute(
                    """
                    SELECT
                        m.domain AS domain,
                        COUNT(m.id) AS count,
                        MAX(m.timestamp) AS last_updated,
                        (
                            SELECT payload
                            FROM memories m2
                            WHERE m2.domain = m.domain
                            ORDER BY m2.id DESC
                            LIMIT 1
                        ) AS payload
                    FROM memories m
                    GROUP BY m.domain
                    ORDER BY last_updated DESC
                    """
                ) as cursor:
                    rows = await cursor.fetchall()

            results = []
            for row in rows:
                domain, count, last_updated, payload_raw = row
                if not domain:
                    continue
                try:
                    payload = json.loads(payload_raw) if payload_raw else {}
                    preview_src = payload_raw if isinstance(payload_raw, str) else str(payload)
                    preview_src = (
                        preview_src.strip() if isinstance(preview_src, str) else str(preview_src)
                    )
                    preview = preview_src[:200] + ("..." if len(preview_src) > 200 else "")
                except Exception:
                    payload = {"raw": payload_raw}
                    preview_src = str(payload_raw or "")
                    preview = preview_src[:200] + ("..." if len(preview_src) > 200 else "")
                results.append(
                    {
                        "domain": domain,
                        "count": count,
                        "last_updated": str(last_updated),
                        "payload_preview": preview,
                        "full_payload": payload,
                    }
                )
            await self.domain_stats_cache.put(cache_key, results)
            return results
        except Exception as e:
            logger.error(_laym_t("laym.err.list_mem", e=e))
            return []

    async def shutdown(self):
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        await self.short_term.cleanup_expired()
        logger.info(_laym_t("laym.log.shutdown"))


# --- END OF FILE src/adami_kernel/hippocampus/layered_memory.py ---
