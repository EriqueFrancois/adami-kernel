import asyncio
import logging
import os

# 尝试导入 ChromaDB
try:
    import chromadb

    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False

from adami_kernel.config import settings
from adami_kernel.i18n import t as i18n_t

logger = logging.getLogger("AdamI-Episodic")


def _epis_t(key: str, **kwargs: object) -> str:
    return i18n_t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class EpisodicMemory:
    """
    AdamI 情景记忆区 (Episodic Memory)
    基于 ChromaDB 的长期向量记忆库。
    核心功能：在遗忘底层流水账前，将带有教训的“错题”进行 Embedding 存储，并在相似场景下唤醒回忆。
    【重要】：本文件是 recall_errors / save_error 的唯一实现源，dream_sandbox.py 只负责调用
    """

    def __init__(self, db_path=None):
        if db_path is None:
            db_path = settings.path_episodic_vector_db
        self.enabled = CHROMA_AVAILABLE
        if not self.enabled:
            logger.warning(_epis_t("epis.log.chroma_missing"))
            return

        os.makedirs(db_path, exist_ok=True)
        # 初始化 ChromaDB 本地持久化客户端
        try:
            self.client = chromadb.PersistentClient(path=db_path)
            # 获取或创建“错题本”集合
            self.error_collection = self.client.get_or_create_collection(name="error_logbook")
            logger.debug("[EpisodicMemory] Chroma error_logbook collection ready")
        except Exception as e:
            logger.error(_epis_t("epis.log.init_fail", err=e))
            self.enabled = False

    # ====================== 【异步错题本写入】 ======================
    async def save_error(self, task: str, action: str, bad_code: str, error_msg: str):
        """将惨痛的教训刻入错题本（异步版）"""
        if not self.enabled:
            return

        # 使用哈希生成唯一 ID 防止重复记录完全相同的错误
        doc_id = f"err_{hash(bad_code + error_msg)}"
        document = _epis_t(
            "epis.doc.save",
            task=task,
            action=action,
            bad_code=bad_code,
            error_msg=error_msg,
        )
        metadatas = {"type": "error", "action": action}

        try:
            await asyncio.to_thread(
                self.error_collection.upsert,
                documents=[document],
                metadatas=[metadatas],
                ids=[doc_id],
            )
            logger.info(_epis_t("epis.log.saved", action=action))
        except Exception as e:
            logger.error(_epis_t("epis.log.save_fail", err=e))

    # =================================================================================

    # ====================== 【异步回忆错题本】 ======================
    async def recall_errors(
        self, current_task: str, current_action: str, n_results: int = 2
    ) -> str:
        """根据当前意图，通过 Vector Search 唤醒相关的历史教训（异步版）"""
        if not self.enabled or self.error_collection.count() == 0:
            return ""

        query_text = _epis_t(
            "epis.query.recall",
            current_task=current_task,
            current_action=current_action,
        )
        try:
            # 使用 to_thread 包装同步的 ChromaDB query 操作
            results = await asyncio.to_thread(
                self.error_collection.query,
                query_texts=[query_text],
                n_results=min(n_results, self.error_collection.count()),
            )

            documents = results.get("documents", [[]])[0]
            if not documents:
                return ""

            recall_str = _epis_t("epis.recall.header")
            for i, doc in enumerate(documents):
                recall_str += _epis_t("epis.recall.item", idx=i + 1, doc=doc)

            logger.info(_epis_t("epis.log.recall_ok", n=len(documents)))
            return recall_str

        except Exception as e:
            logger.error(_epis_t("epis.log.recall_fail", err=e))
            return ""

    # =================================================================================
