# --- START OF FILE subconscious.py ---

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List

import aiosqlite
import httpx
import numpy as np

from adami_kernel.config import settings
from adami_kernel.hippocampus.db_helper import DatabaseHelper
from adami_kernel.i18n import t
from adami_kernel.i18n.boot_msg import boot_t

logger = logging.getLogger("Hippocampus-Subconscious")


def _subc_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class SubconsciousRAG:
    """
    潜意识 RAG：负责记忆巩固、本能反射与探索去重 (工业级适配版)
    【修复 1】：彻底移除内部自我管理的 DB 连接，全权委托 DatabaseHelper，防死锁。
    【修复 2】：在睡眠提炼的 for 循环外建立统一的 HTTP 连接池，消除 TLS 握手风暴，提升百倍速度。
    【本次核心修复】：全面引入 async with cursor 游标上下文管理器，彻底杜绝高频查询导致的 Cursor 泄漏和文件句柄堆积。
    """

    def __init__(self, db_path=None, memory=None):
        self.db_path = db_path if db_path is not None else settings.path_subconscious_db
        self.memory = memory

        # 优先使用 GEMINI_API_KEY，如果没有则回退 LLM_API_KEY
        self.api_key = settings.GEMINI_API_KEY or settings.LLM_API_KEY
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

        self.model_name = settings.ADAMI_SUBCONSCIOUS_MODEL

        self._pseudo_hit_count = 0
        self.recent_explorations: Dict[str, datetime] = {}
        self.cache_ttl = timedelta(minutes=30)

    async def _get_conn(self) -> aiosqlite.Connection:
        """【安全重构】直接向 DatabaseHelper 索要持久化连接，不再自行缓存"""
        return await DatabaseHelper.get_aiosqlite_conn(self.db_path)

    async def initialize(self):
        await DatabaseHelper.ensure_wal(self.db_path)

        conn = await self._get_conn()
        # 【核心修复】使用游标上下文管理器，防止初始化时产生游离 Cursor
        async with conn.cursor() as cursor:
            await cursor.execute(
                "CREATE TABLE IF NOT EXISTS instincts (id INTEGER PRIMARY KEY AUTOINCREMENT, lesson TEXT, embedding TEXT)"
            )
            await cursor.execute("CREATE TABLE IF NOT EXISTS sleep_log (last_processed_id INTEGER)")
            await cursor.execute("SELECT COUNT(*) FROM sleep_log")
            count = (await cursor.fetchone())[0]
            if count == 0:
                await cursor.execute("INSERT INTO sleep_log (last_processed_id) VALUES (0)")
        await conn.commit()
        logger.info(boot_t("boot.log.subconscious_ready"))

    def filter_redundant_exploration(self, target: str) -> bool:
        """判断当前探索目标（URL或关键词）是否重复"""
        now = datetime.now()
        self.recent_explorations = {
            k: v for k, v in self.recent_explorations.items() if now - v < self.cache_ttl
        }

        if target in self.recent_explorations:
            logger.info(_subc_t("subc.log.dup_explore", target=target))
            return False

        self.recent_explorations[target] = now
        return True

    async def _get_embedding(self, text: str) -> List[float]:
        if not self.api_key:
            return [0.0] * 768

        headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
        payload = {"content": {"parts": [{"text": text}]}, "task_type": "RETRIEVAL_DOCUMENT"}
        models = ["models/text-embedding-004", "models/embedding-001"]

        # 为了兼容多模型的 fallback，此处保持内部上下文管理器，但增加重试机制
        async with httpx.AsyncClient(
            timeout=10.0, limits=httpx.Limits(max_connections=10)
        ) as client:
            for model_id in models:
                try:
                    url = f"{self.base_url}/{model_id}:embedContent"
                    resp = await client.post(url, headers=headers, json=payload)
                    if resp.status_code == 200:
                        self._pseudo_hit_count = 0
                        return resp.json()["embedding"]["values"]
                except Exception as e:
                    logger.debug(_subc_t("subc.debug.embed_fail", model=model_id, e=e))
                    continue

        self._pseudo_hit_count += 1
        return [0.0] * 768

    async def retrieve_instincts(self, query: str, top_k: int = 1) -> str:
        query_emb = await self._get_embedding(query)
        if not query_emb or all(v == 0.0 for v in query_emb):
            return ""

        q_vec = np.array(query_emb)
        instincts = []

        conn = await self._get_conn()
        conn.row_factory = aiosqlite.Row

        # 【核心修复】高频查询，必须使用上下文管理器安全释放 Cursor
        async with conn.execute("SELECT lesson, embedding FROM instincts") as cursor:
            rows = await cursor.fetchall()

        for row in rows:
            try:
                emb = np.array(json.loads(row["embedding"]))
                if all(v == 0.0 for v in emb):
                    continue
                similarity = np.dot(q_vec, emb) / (np.linalg.norm(q_vec) * np.linalg.norm(emb))
                instincts.append((similarity, row["lesson"]))
            except Exception as e:
                # 记录数据库中损坏的向量记录，而非无声吞没
                logger.warning(_subc_t("subc.warn.vec_parse", e=e))
                continue

        if not instincts:
            return ""

        instincts.sort(key=lambda x: x[0], reverse=True)
        return instincts[0][1] if instincts[0][0] > 0.65 else ""

    async def sleep_and_consolidate(self):
        """REM 睡眠期间的记忆整理与历史刷新"""
        logger.info(_subc_t("subc.log.rem_start"))
        self.recent_explorations.clear()

        if hasattr(self.memory, "retrieve_recent"):
            raw_experiences = await self.memory.retrieve_recent("code_ops", limit=200)
        else:
            logger.warning(_subc_t("subc.warn.no_memory"))
            raw_experiences = []

        if not raw_experiences:
            return

        tasks = {}
        for exp in raw_experiences:
            tid = exp.get("trace_id", "unknown")
            if tid not in tasks:
                tasks[tid] = []
            tasks[tid].append(exp)

        openai_key = settings.OPENAI_API_KEY or settings.LLM_API_KEY
        base_url = settings.LLM_BASE_URL
        model = settings.ADAMI_SUBCONSCIOUS_MODEL

        if not openai_key:
            logger.warning(_subc_t("subc.warn.no_openai_key"))
            return

        success_count = 0
        # 【核心修复】：在 for 循环的外部建立连接池，实现连接复用，避免 TLS 握手风暴
        async with httpx.AsyncClient(
            timeout=30.0, limits=httpx.Limits(max_keepalive_connections=10)
        ) as client:
            for tid, logs in tasks.items():
                if len(logs) < 2:
                    continue

                prompt = (
                    boot_t("cjk_gate.subconscious_extract_prompt_prefix")
                    + json.dumps(logs, ensure_ascii=False)[:2000]
                )

                try:
                    resp = await client.post(
                        base_url + "/chat/completions",
                        headers={"Authorization": f"Bearer {openai_key}"},
                        json={"model": model, "messages": [{"role": "user", "content": prompt}]},
                    )

                    if resp.status_code == 200:
                        lesson = resp.json()["choices"][0]["message"]["content"].strip()
                        if lesson and "None" not in lesson:
                            emb = await self._get_embedding(lesson)
                            conn = await self._get_conn()

                            # 【核心修复】写入数据时严格使用游标上下文管理器
                            async with conn.cursor() as cursor:
                                await cursor.execute(
                                    "INSERT INTO instincts (lesson, embedding) VALUES (?, ?)",
                                    (lesson, json.dumps(emb)),
                                )
                            await conn.commit()

                            success_count += 1
                except Exception as e:
                    logger.warning(_subc_t("subc.warn.rem_tid_fail", tid=tid, e=e))
                    continue

        logger.info(_subc_t("subc.log.rem_done", ok=success_count, total=len(tasks)))


# --- END OF FILE subconscious.py ---
