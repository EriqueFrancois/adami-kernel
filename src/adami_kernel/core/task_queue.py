from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Tuple, cast

if TYPE_CHECKING:
    from adami_kernel.config import Settings

logger = logging.getLogger("AdamI-TaskQueue")


@dataclass(frozen=True)
class QueuedTask:
    id: str
    task: str
    chat_id: str
    source_module: str
    platform: str
    created_at: float
    # Original user prompt trace_id (preserves DecisionProcessor reply idempotency across queue dispatch).
    trace_id: str = ""
    # Optional marker for tasks recovered from a previous in-progress run.
    recovered_from: str = ""


@dataclass(frozen=True)
class InProgressTask:
    id: str
    task: str
    chat_id: str
    source_module: str
    platform: str
    started_at: float
    trace_id: str


def _try_fernet(key: Optional[str]) -> Any:
    if not key or not str(key).strip():
        return None
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        logger.warning(
            "ADAMI_TASK_QUEUE_FERNET_KEY is set but cryptography is not installed; "
            "queue file will stay plaintext."
        )
        return None
    try:
        return Fernet(str(key).strip().encode("utf-8"))
    except Exception as e:
        logger.warning("Invalid ADAMI_TASK_QUEUE_FERNET_KEY; queue encryption disabled: %s", e)
        return None


class TaskQueueStore:
    """
    Per-chat task queue with JSON persistence (optional Fernet-at-rest).

    - TTL: pending ``QueuedTask`` rows older than ``ttl_sec`` are dropped on load / save / enqueue.
    - Caps: ``max_per_chat`` drops oldest pending when exceeded; ``max_total`` trims longest queues.
    - Encryption: when ``fernet`` is valid, disk format ``adami_task_queue/v2`` with encrypted inner JSON.
    """

    _FORMAT_V2 = "adami_task_queue/v2"

    def __init__(
        self,
        path: Path,
        *,
        ttl_sec: float = 0.0,
        in_progress_ttl_sec: float = 0.0,
        max_per_chat: int = 0,
        max_total: int = 0,
        overflow_mode: Literal["drop_oldest", "reject"] = "drop_oldest",
        fernet_key: Optional[str] = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ttl_sec = max(0.0, float(ttl_sec or 0.0))
        self._in_progress_ttl_sec = max(0.0, float(in_progress_ttl_sec or 0.0))
        self._max_per_chat = max(0, int(max_per_chat or 0))
        self._max_total = max(0, int(max_total or 0))
        om = str(overflow_mode or "drop_oldest").strip().lower()
        self._overflow_mode: Literal["drop_oldest", "reject"] = (
            "reject" if om == "reject" else "drop_oldest"
        )
        self._fernet = _try_fernet(fernet_key)
        self._queues: Dict[str, List[QueuedTask]] = {}
        self._in_progress: Dict[str, InProgressTask] = {}
        self._load()

    @classmethod
    def from_settings(cls, s: Settings) -> TaskQueueStore:
        return cls(
            s.path_task_queue_json,
            ttl_sec=float(getattr(s, "ADAMI_TASK_QUEUE_TTL_SEC", 0.0) or 0.0),
            in_progress_ttl_sec=float(
                getattr(s, "ADAMI_TASK_QUEUE_IN_PROGRESS_TTL_SEC", 0.0) or 0.0
            ),
            max_per_chat=int(getattr(s, "ADAMI_TASK_QUEUE_MAX_PER_CHAT", 0) or 0),
            max_total=int(getattr(s, "ADAMI_TASK_QUEUE_MAX_TOTAL", 0) or 0),
            overflow_mode=getattr(s, "ADAMI_TASK_QUEUE_OVERFLOW_MODE", "drop_oldest"),
            fernet_key=getattr(s, "ADAMI_TASK_QUEUE_FERNET_KEY", None),
        )

    def _purge_stale(self) -> Tuple[int, int]:
        now = time.time()
        removed = 0
        removed_ip = 0
        if self._ttl_sec > 0:
            cutoff = now - self._ttl_sec
            for cid, items in list(self._queues.items()):
                kept = [x for x in items if x.created_at >= cutoff]
                removed += len(items) - len(kept)
                if kept:
                    self._queues[cid] = kept
                else:
                    self._queues.pop(cid, None)
            if removed:
                logger.info("Task queue TTL dropped %s pending item(s).", removed)

        if self._in_progress_ttl_sec > 0:
            ip_cutoff = now - self._in_progress_ttl_sec
            for cid, it in list(self._in_progress.items()):
                try:
                    if float(it.started_at) < ip_cutoff:
                        self._in_progress.pop(cid, None)
                        removed_ip += 1
                except Exception:
                    continue
            if removed_ip:
                logger.warning(
                    "Task queue TTL dropped %s in-progress item(s) (stale start time).",
                    removed_ip,
                )
        return removed, removed_ip

    def persist_after_purge(self) -> Tuple[int, int]:
        """Drop TTL-expired rows and write the file when anything changed."""
        removed, removed_ip = self._purge_stale()
        if removed or removed_ip:
            self._save()
        return removed, removed_ip

    def _total_pending(self) -> int:
        return sum(len(v) for v in self._queues.values())

    def _enforce_max_per_chat(self, chat_id: str) -> int:
        if self._max_per_chat <= 0:
            return 0
        cid = str(chat_id)
        q = self._queues.setdefault(cid, [])
        dropped = 0
        while len(q) > self._max_per_chat:
            q.pop(0)
            dropped += 1
        if dropped:
            logger.warning(
                "Task queue per-chat cap (%s): dropped %s oldest pending for chat_id=%s",
                self._max_per_chat,
                dropped,
                cid,
            )
        return dropped

    def _enforce_max_total(self) -> int:
        if self._max_total <= 0:
            return 0
        dropped = 0
        while self._total_pending() > self._max_total:
            best_cid: Optional[str] = None
            best_len = -1
            for cid, items in self._queues.items():
                if len(items) > best_len:
                    best_len = len(items)
                    best_cid = cid
            if not best_cid or best_len <= 0:
                break
            lst = self._queues.get(best_cid) or []
            if not lst:
                break
            lst.pop(0)
            dropped += 1
            if not lst:
                self._queues.pop(best_cid, None)
            logger.warning(
                "Task queue global cap (%s): dropped oldest pending from chat_id=%s",
                self._max_total,
                best_cid,
            )
        return dropped

    def _hydrate_from_data(self, data: Dict[str, Any]) -> None:
        self._queues.clear()
        self._in_progress.clear()
        queues = data.get("queues")
        if isinstance(queues, dict):
            for cid, items in cast(Dict[str, Any], queues).items():
                if not isinstance(items, list):
                    continue
                out: List[QueuedTask] = []
                for it in cast(List[Any], items):
                    if not isinstance(it, dict):
                        continue
                    row = cast(Dict[str, Any], it)
                    try:
                        out.append(
                            QueuedTask(
                                id=str(row.get("id") or ""),
                                task=str(row.get("task") or ""),
                                chat_id=str(row.get("chat_id") or cid),
                                source_module=str(row.get("source_module") or "user.prompt"),
                                platform=str(row.get("platform") or "cli"),
                                created_at=float(row.get("created_at") or 0.0),
                                trace_id=str(row.get("trace_id") or ""),
                                recovered_from=str(row.get("recovered_from") or ""),
                            )
                        )
                    except Exception:
                        continue
                if out:
                    self._queues[str(cid)] = out
        ip = data.get("in_progress")
        if isinstance(ip, dict):
            for cid, it in cast(Dict[str, Any], ip).items():
                if not isinstance(it, dict):
                    continue
                row = cast(Dict[str, Any], it)
                try:
                    self._in_progress[str(cid)] = InProgressTask(
                        id=str(row.get("id") or ""),
                        task=str(row.get("task") or ""),
                        chat_id=str(row.get("chat_id") or cid),
                        source_module=str(row.get("source_module") or "user.prompt"),
                        platform=str(row.get("platform") or "cli"),
                        started_at=float(row.get("started_at") or 0.0),
                        trace_id=str(row.get("trace_id") or ""),
                    )
                except Exception:
                    continue

    def _load(self) -> None:
        try:
            if not self.path.exists():
                return
            raw = self.path.read_text(encoding="utf-8")
            if not raw.strip():
                return
            outer_any = json.loads(raw)
            if not isinstance(outer_any, dict):
                return
            outer = cast(Dict[str, Any], outer_any)
            if outer.get("format") == self._FORMAT_V2 and self._fernet is not None:
                blob = outer.get("blob")
                if not isinstance(blob, str):
                    return
                try:
                    inner_bytes = self._fernet.decrypt(blob.encode("ascii"))
                    inner_obj = json.loads(inner_bytes.decode("utf-8"))
                except Exception as e:
                    logger.error("Task queue decrypt failed; starting empty: %s", e)
                    return
                if not isinstance(inner_obj, dict):
                    return
                self._hydrate_from_data(cast(Dict[str, Any], inner_obj))
            else:
                self._hydrate_from_data(outer)
            self._purge_stale()
        except Exception as e:
            logger.warning("Task queue load failed (non-fatal): %s", e)

    def _inner_payload_dict(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "queues": {cid: [asdict(x) for x in items] for cid, items in self._queues.items()},
            "in_progress": {cid: asdict(x) for cid, x in self._in_progress.items()},
            "saved_at": time.time(),
        }

    def _save(self) -> None:
        try:
            self._purge_stale()
            inner = self._inner_payload_dict()
            inner_json = json.dumps(inner, ensure_ascii=False, indent=2).encode("utf-8")
            if self._fernet is not None:
                token = self._fernet.encrypt(inner_json)
                # ``token`` is already URL-safe base64 ASCII from Fernet.
                blob = token.decode("ascii")
                payload: Dict[str, Any] = {
                    "format": self._FORMAT_V2,
                    "saved_at": time.time(),
                    "blob": blob,
                }
                text = json.dumps(payload, ensure_ascii=False, indent=2)
            else:
                text = inner_json.decode("utf-8")
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(self.path)
        except Exception as e:
            logger.warning("Task queue save failed (non-fatal): %s", e)

    def enqueue(
        self,
        *,
        chat_id: str,
        task: str,
        source_module: str,
        platform: str,
        trace_id: str = "",
    ) -> Optional[QueuedTask]:
        cid = str(chat_id)
        text = str(task or "").strip()
        if not text:
            return None
        self._purge_stale()
        now = time.time()
        qid = f"q_{int(now * 1000)}"
        item = QueuedTask(
            id=qid,
            task=text,
            chat_id=cid,
            source_module=str(source_module or "user.prompt"),
            platform=str(platform or "cli"),
            created_at=now,
            trace_id=str(trace_id or ""),
        )
        q = self._queues.setdefault(cid, [])
        if self._overflow_mode == "reject":
            if self._max_total > 0 and self._total_pending() >= self._max_total:
                logger.warning("Task queue reject (global cap): chat_id=%s", cid)
                return None
            if self._max_per_chat > 0 and len(q) >= self._max_per_chat:
                logger.warning("Task queue reject (per-chat cap): chat_id=%s", cid)
                return None
            q.append(item)
        else:
            q.append(item)
            self._enforce_max_per_chat(cid)
            self._enforce_max_total()
        self._save()
        return item

    def list_pending(self, chat_id: str) -> List[QueuedTask]:
        self._purge_stale()
        return list(self._queues.get(str(chat_id), []))

    def get_in_progress(self, chat_id: str) -> Optional[InProgressTask]:
        return self._in_progress.get(str(chat_id))

    def has_pending_or_in_progress(self, chat_id: str) -> bool:
        cid = str(chat_id)
        return bool(self._queues.get(cid)) or (cid in self._in_progress)

    def pop_next(self, chat_id: str) -> Optional[QueuedTask]:
        self._purge_stale()
        cid = str(chat_id)
        items = self._queues.get(cid) or []
        if not items:
            return None
        nxt = items.pop(0)
        if not items:
            self._queues.pop(cid, None)
        self._save()
        return nxt

    def mark_started(
        self,
        *,
        chat_id: str,
        trace_id: str,
        task: str,
        source_module: str,
        platform: str,
    ) -> None:
        cid = str(chat_id)
        now = time.time()
        self._in_progress[cid] = InProgressTask(
            id=f"run_{int(now * 1000)}",
            task=str(task or "").strip(),
            chat_id=cid,
            source_module=str(source_module or "user.prompt"),
            platform=str(platform or "cli"),
            started_at=now,
            trace_id=str(trace_id),
        )
        self._save()

    def mark_finished(self, chat_id: str) -> None:
        cid = str(chat_id)
        if cid in self._in_progress:
            self._in_progress.pop(cid, None)
            self._save()

    def discard_all(self, chat_id: str) -> Tuple[int, bool]:
        cid = str(chat_id)
        n = len(self._queues.get(cid) or [])
        had_ip = cid in self._in_progress
        self._queues.pop(cid, None)
        self._in_progress.pop(cid, None)
        self._save()
        return n, had_ip

    def chat_ids_with_pending(self) -> List[str]:
        self._purge_stale()
        ids = set(self._queues.keys()) | set(self._in_progress.keys())
        return sorted(str(x) for x in ids if str(x).strip())

    def preferred_platform(self, chat_id: str) -> str:
        cid = str(chat_id)
        ip = self._in_progress.get(cid)
        if ip is not None and str(ip.platform).strip():
            return str(ip.platform).strip()
        qs = self._queues.get(cid) or []
        if qs and str(qs[0].platform).strip():
            return str(qs[0].platform).strip()
        return "telegram" if cid.isdigit() else "discord"

    def recover_in_progress_to_front(self, chat_id: str) -> Optional[QueuedTask]:
        cid = str(chat_id)
        ip = self._in_progress.get(cid)
        if ip is None or not ip.task.strip():
            return None
        try:
            age_anchor = float(ip.started_at)
        except (TypeError, ValueError):
            age_anchor = time.time()
        item = QueuedTask(
            id=f"re_{ip.id}",
            task=ip.task,
            chat_id=cid,
            source_module=ip.source_module,
            platform=ip.platform,
            created_at=age_anchor,
            trace_id=str(getattr(ip, "trace_id", "") or ""),
            recovered_from=f"in_progress:{str(getattr(ip, 'id', '') or '').strip() or 'unknown'}",
        )
        self._queues.setdefault(cid, []).insert(0, item)
        self._in_progress.pop(cid, None)
        self._save()
        return item
