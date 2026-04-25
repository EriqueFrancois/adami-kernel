# --- START OF FILE vector_store.py ---
# src/adami_kernel/skill_manager/vector_store.py
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import chromadb
    from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction

    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False

from adami_kernel.config import settings
from adami_kernel.cortex.router import LLMRouter
from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.i18n import t as i18n_t
from adami_kernel.i18n.boot_msg import boot_t

logger = logging.getLogger("AdamI-VectorStore")


def _vs_t(key: str, **kwargs: Any) -> str:
    return i18n_t(key, locale=settings.effective_ui_default_locale(), **kwargs)


def _bad_skill_name_markers() -> List[str]:
    return json.loads(_vs_t("vs.bad_markers_json"))


if not CHROMA_AVAILABLE:
    logger.warning(boot_t("boot.log.vector_chroma_missing"))


class VectorStore:
    """
    技能向量化存储与检索组件（Phase 2）
    基于 ChromaDB 实现技能语义搜索，使用 OpenAI 嵌入 API。
    【Phase 1 强化】在 initialize / add_skill 时自动清理污染残留。
    【最终修复】清空集合安全删除 + 嵌入模型异常处理 + SkillManager 注入日志加强
    """

    def __init__(
        self,
        memory: LayeredMemory,
        llm_router: Optional[LLMRouter] = None,
        chroma_client: Optional[chromadb.Client] = None,
    ):
        self.memory = memory
        self.llm_router = llm_router
        self.client = chroma_client
        self.collection = None
        self._initialized = False
        self._embedding_fn = None
        self._fallback_mode: bool = False

    @staticmethod
    def _flatten_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        将嵌套的 metadata 扁平化，将 dict/list 转换为 JSON 字符串，
        以符合 ChromaDB 的 metadata 限制（只支持 str, int, float, bool, list, None）。
        """
        if not metadata:
            return {}
        result = {}
        for key, value in metadata.items():
            if isinstance(value, dict):
                result[key] = json.dumps(value, ensure_ascii=False)
            elif isinstance(value, list):
                # 列表中的元素如果是 dict，也转为 JSON
                try:
                    result[key] = json.dumps(value, ensure_ascii=False)
                except TypeError:
                    result[key] = str(value)
            elif isinstance(value, (str, int, float, bool)) or value is None:
                result[key] = value
            else:
                # 其他类型（如 datetime）转为字符串
                result[key] = str(value)
        return result

    async def initialize(self):
        """初始化 ChromaDB 客户端和技能集合（OpenAI 嵌入 API）"""
        if self._initialized:
            logger.debug(_vs_t("vs.log.already_init"))
            return

        if not CHROMA_AVAILABLE:
            logger.error(_vs_t("vs.err.chroma_unavailable"))
            return

        try:
            if self.client is None:
                self.client = chromadb.PersistentClient(path=settings.path_chroma_persist_dir)
                logger.info(boot_t("boot.log.vector_new_client"))
            else:
                logger.info(boot_t("boot.log.vector_reuse_client"))

            # ====================== 使用 OpenAI 嵌入 API ======================
            api_key = settings.OPENAI_API_KEY
            if api_key:
                try:
                    self._embedding_fn = OpenAIEmbeddingFunction(
                        api_key=api_key, model_name="text-embedding-ada-002"
                    )
                    self._fallback_mode = False
                    logger.info(boot_t("boot.log.vector_embed_ok", model="text-embedding-ada-002"))
                except Exception as e:
                    logger.warning(
                        boot_t("boot.log.vector_embed_fail", detail=str(e)), exc_info=True
                    )
                    self._embedding_fn = None
                    self._fallback_mode = True
            else:
                logger.warning(boot_t("boot.log.vector_no_openai_key"))
                self._embedding_fn = None
                self._fallback_mode = True
            # =================================================================

            embedding_arg = {"embedding_function": self._embedding_fn} if self._embedding_fn else {}
            self.collection = self.client.get_or_create_collection(
                name="skill_vectors", **embedding_arg
            )
            self._initialized = True
            logger.info(boot_t("boot.log.vector_skill_store_init", fallback=self._fallback_mode))

            # 【Phase 1 核心】自动清理残留坏技能
            await self._cleanup_bad_skills()

        except Exception as e:
            logger.error(_vs_t("vs.log.init_fail", err=e), exc_info=True)
            self._initialized = False

    async def _cleanup_bad_skills(self):
        """【Phase 1 新增】自动清理残留坏技能（名称包含提示文本的污染条目）"""
        if not self._initialized or not self.collection:
            return
        try:
            all_metadata = await self.memory.retrieve_recent(
                domain="skill_metadata", limit=1000, chat_id="system"
            )
            by_skill: Dict[str, Dict[str, Any]] = {}
            for meta in all_metadata or []:
                sn = (meta.get("skill_name") or "").strip().upper()
                if sn:
                    by_skill[sn] = meta
            bad_count = 0
            for skill_name, _meta in by_skill.items():
                if any(bad in skill_name for bad in _bad_skill_name_markers()):
                    await self.remove_skill(skill_name)
                    bad_count += 1
            if bad_count > 0:
                logger.info(boot_t("boot.log.vector_cleanup_bad", count=bad_count))
            else:
                logger.info(boot_t("boot.log.vector_cleanup_none"))
        except Exception as e:
            logger.warning(_vs_t("vs.log.cleanup_fail", err=e), exc_info=True)

    async def rebuild_index(self):
        if not self._initialized:
            logger.warning(_vs_t("vs.warn.not_init_rebuild"))
            return

        all_metadata = await self.memory.retrieve_recent(
            domain="skill_metadata", limit=1000, chat_id="system"
        )
        if not all_metadata:
            logger.info(_vs_t("vs.log.no_meta"))
            return

        # 按 skill_name 去重；retrieve_recent 为旧→新顺序，后写覆盖前写 → 保留最新记录
        unique_skills: Dict[str, Dict[str, Any]] = {}
        for meta in all_metadata:
            skill_name = (meta.get("skill_name") or "").strip().upper()
            if not skill_name:
                continue
            unique_skills[skill_name] = meta

        ids: List[str] = []
        documents: List[str] = []
        metadatas: List[Dict[str, Any]] = []

        for skill_name, meta in unique_skills.items():
            versions = meta.get("versions", {})
            current_ver = meta.get("current_version", "v1.0")
            version_info = versions.get(current_ver, {})
            if not isinstance(version_info, dict):
                version_info = {}
            description = version_info.get("description", "")

            doc_text = f"{skill_name} {description}".strip()
            if not doc_text:
                continue

            doc_id = f"skill_{skill_name}"
            ids.append(doc_id)
            documents.append(doc_text)
            flat_meta = self._flatten_metadata(
                {
                    "skill_name": skill_name,
                    "description": description,
                    "status": meta.get("status", "active"),
                    "score": meta.get("score", 100.0),
                }
            )
            metadatas.append(flat_meta)

        if not ids:
            logger.info(_vs_t("vs.log.no_meta"))
            return

        fp_payload = "\n".join(f"{i}|{d}" for i, d in sorted(zip(ids, documents, strict=False)))
        fp = hashlib.sha256(fp_payload.encode("utf-8")).hexdigest()
        fp_path = Path(settings.adami_data_dir_path) / "vector_store_skill_vectors.sha256"
        skip_rebuild = getattr(settings, "ADAMI_VECTOR_STORE_SKIP_REBUILD_IF_UNCHANGED", True)
        if skip_rebuild and fp_path.is_file():
            try:
                prev = fp_path.read_text(encoding="utf-8").strip()
            except OSError:
                prev = ""
            try:
                cur_count = int(self.collection.count())  # type: ignore[union-attr]
            except Exception:
                cur_count = -1
            if prev == fp and cur_count == len(ids):
                logger.info(_vs_t("vs.log.rebuild_skip", n=len(ids)))
                return

        try:
            existing = self.collection.get()  # type: ignore[union-attr]
            ex_ids = set(existing.get("ids") or [])
            desired = set(ids)
            orphans = ex_ids - desired
            if orphans:
                self.collection.delete(ids=list(orphans))  # type: ignore[union-attr]
                logger.info(_vs_t("vs.log.rebuild_orphans", n=len(orphans)))
        except Exception as e:
            logger.warning(_vs_t("vs.log.clear_fail", err=e), exc_info=True)

        try:
            if self._fallback_mode or self._embedding_fn is None:
                self.collection.upsert(ids=ids, documents=documents, metadatas=metadatas)  # type: ignore[union-attr]
                logger.info(_vs_t("vs.log.rebuild_fallback", n=len(ids)))
            else:
                self.collection.upsert(ids=ids, documents=documents, metadatas=metadatas)  # type: ignore[union-attr]
                logger.info(boot_t("boot.log.vector_reindex_ok", count=len(ids)))
            fp_path.parent.mkdir(parents=True, exist_ok=True)
            fp_path.write_text(fp, encoding="utf-8")
        except Exception as e:
            logger.error(_vs_t("vs.log.upsert_fail", err=e), exc_info=True)

    async def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        if not self._initialized:
            logger.warning(_vs_t("vs.warn.not_init_search"))
            return []

        # Empty query: list-all-skills style paths; skip embeddings (OpenAI rejects empty input).
        if query is None or not str(query).strip():
            try:
                got = self.collection.get(include=["metadatas", "documents"])
                metadatas = got.get("metadatas", []) or []
                documents = got.get("documents", []) or []
                out: List[Dict[str, Any]] = []
                for meta, doc in zip(metadatas, documents, strict=False):
                    out.append(
                        {
                            "skill_name": (meta or {}).get("skill_name", ""),
                            "description": (meta or {}).get("description", ""),
                            "content": doc,
                            "distance": None,
                            "metadata": meta or {},
                        }
                    )
                return out
            except Exception as e:
                logger.error(_vs_t("vs.log.empty_get_fail", err=e), exc_info=True)
                return []

        try:
            if self._fallback_mode or self._embedding_fn is None:
                results = self.collection.query(
                    query_texts=[query],
                    n_results=top_k,
                    include=["metadatas", "documents", "distances"],
                )
                logger.info(_vs_t("vs.log.fallback_search", query=query))
            else:
                results = self.collection.query(
                    query_texts=[query],
                    n_results=top_k,
                    include=["metadatas", "documents", "distances"],
                )

            metadatas = results.get("metadatas", [[]])[0]
            documents = results.get("documents", [[]])[0]
            distances = results.get("distances", [[]])[0]

            skills = []
            for i, meta in enumerate(metadatas):
                # 尝试解析可能为 JSON 字符串的字段（如 metrics）
                for key in list(meta.keys()):
                    if (
                        isinstance(meta.get(key), str)
                        and meta[key].startswith("{")
                        and meta[key].endswith("}")
                    ):
                        try:
                            meta[key] = json.loads(meta[key])
                        except (json.JSONDecodeError, TypeError, ValueError):
                            pass
                skills.append(
                    {
                        "skill_name": meta.get("skill_name"),
                        "description": meta.get("description"),
                        "document": documents[i],
                        "distance": distances[i],
                    }
                )
            return skills
        except Exception as e:
            logger.error(_vs_t("vs.log.search_fail", err=e), exc_info=True)
            return []

    async def add_skill(self, skill_name: str, description: str, metadata: Dict[str, Any] = None):
        skill_name = (skill_name or "").strip().upper()
        if not skill_name:
            return
        # 如果未初始化，尝试初始化（处理异步初始化未完成的情况）
        if not self._initialized:
            logger.warning(_vs_t("vs.warn.add_not_init", skill_name=skill_name))
            await self.initialize()
            if not self._initialized:
                logger.warning(_vs_t("vs.warn.add_init_fail", skill_name=skill_name))
                return

        doc_text = f"{skill_name} {description}".strip()
        if not doc_text:
            return

        doc_id = f"skill_{skill_name}"
        # 扁平化 metadata，移除嵌套结构
        if metadata is None:
            meta = {}
        else:
            # 只保留顶层基本类型字段，将嵌套字段转为 JSON
            meta = self._flatten_metadata(metadata)

        # 确保必需字段存在
        meta["skill_name"] = skill_name
        meta["description"] = description

        try:
            if self._fallback_mode or self._embedding_fn is None:
                self.collection.upsert(ids=[doc_id], documents=[doc_text], metadatas=[meta])
                logger.info(_vs_t("vs.log.add_fallback", skill_name=skill_name))
            else:
                self.collection.upsert(ids=[doc_id], documents=[doc_text], metadatas=[meta])
                logger.info(_vs_t("vs.log.add_ok", skill_name=skill_name))

            await self._cleanup_bad_skills()
        except Exception as e:
            logger.error(_vs_t("vs.log.add_fail", err=e), exc_info=True)

    async def remove_skill(self, skill_name: str):
        if not self._initialized:
            return

        skill_name = (skill_name or "").strip().upper()
        if not skill_name:
            return
        doc_id = f"skill_{skill_name}"
        try:
            self.collection.delete(ids=[doc_id])
            logger.info(boot_t("boot.log.vector_skill_deleted", name=skill_name))
        except Exception as e:
            logger.error(_vs_t("vs.log.remove_fail", err=e), exc_info=True)

    async def close(self) -> None:
        if self.client:
            logger.info(_vs_t("vs.log.chroma_close"))
