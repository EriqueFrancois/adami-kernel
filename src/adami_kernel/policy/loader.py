# src/adami_kernel/policy/loader.py
"""从 ADAMI_POLICY_DIR 加载 manifest；异步轮询热更新（可选 watchdog 扩展位）。"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
from pathlib import Path
from typing import Any, Callable, List, Optional

from adami_kernel.config import settings
from adami_kernel.i18n.boot_msg import boot_t
from adami_kernel.policy.manifest import PolicyManifest

logger = logging.getLogger("AdamI-PolicyLoader")

# system / user 模板逻辑键顺序（manifest 中未出现的键跳过）
_SYSTEM_TEMPLATE_KEY_ORDER: List[str] = [
    "system_persona",
    "system",
    "extra_instructions",
]
_USER_TEMPLATE_KEYS: List[str] = [
    "user_fragment",
    "task_wrapper",
]

_policy_loader_singleton: Optional["PolicyLoader"] = None
_singleton_lock = threading.Lock()


def set_policy_loader(loader: Optional["PolicyLoader"]) -> None:
    global _policy_loader_singleton
    with _singleton_lock:
        _policy_loader_singleton = loader


def get_policy_loader() -> Optional["PolicyLoader"]:
    with _singleton_lock:
        return _policy_loader_singleton


def load_manifest(policy_dir: Path, manifest_filename: str) -> PolicyManifest:
    """读取并校验 JSON → PolicyManifest（不校 checksum，由调用方决定）。"""
    path = Path(policy_dir) / manifest_filename
    raw = path.read_text(encoding="utf-8")
    return PolicyManifest.model_validate_json(raw)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_manifest_checksums(manifest: PolicyManifest, policy_dir: Path) -> bool:
    """若 ``checksums`` 非空，则仅校验其中列出的相对路径。"""
    if not manifest.checksums:
        return True
    base = Path(policy_dir)
    for rel, expected in manifest.checksums.items():
        rel_norm = rel.replace("\\", "/").lstrip("/")
        fp = (base / rel_norm).resolve()
        try:
            base_res = base.resolve()
            if not str(fp).startswith(str(base_res)):
                logger.warning(boot_t("boot.log.policy_reject_path_traversal", rel=rel))
                return False
        except OSError:
            return False
        if not fp.is_file():
            logger.warning(boot_t("boot.log.policy_checksum_missing_file", rel=rel))
            return False
        actual = _sha256_file(fp)
        exp = expected.lower().removeprefix("sha256:").strip()
        if actual != exp:
            logger.warning(
                boot_t(
                    "boot.log.policy_checksum_mismatch",
                    rel=rel,
                    manifest_prefix=exp[:12],
                    disk_prefix=actual[:12],
                )
            )
            return False
    return True


class PolicyLoader:
    """线程安全持有当前 manifest；reload 失败时保留上一版。"""

    def __init__(
        self,
        policy_dir: Optional[Path] = None,
        *,
        manifest_filename: Optional[str] = None,
        reload_interval_sec: Optional[float] = None,
    ) -> None:
        self.policy_dir = Path(policy_dir or settings.resolved_policy_dir)
        self.manifest_filename = manifest_filename or settings.ADAMI_POLICY_MANIFEST_FILENAME
        self.reload_interval_sec = float(
            reload_interval_sec or settings.ADAMI_POLICY_RELOAD_INTERVAL_SEC
        )
        self._lock = threading.Lock()
        self._manifest: Optional[PolicyManifest] = None
        self._watchdog_observer: Any = None  # 防止 Observer 被 GC
        path = self.policy_dir / self.manifest_filename
        if not path.is_file():
            logger.debug(boot_t("boot.log.policy_no_manifest_file", path=str(path)))
        self.reload_safe()

    @classmethod
    def from_settings(cls) -> PolicyLoader:
        return cls()

    def get_manifest(self) -> Optional[PolicyManifest]:
        with self._lock:
            return self._manifest

    def reload_safe(self) -> None:
        """供轮询 / 文件监视调用；失败保留旧 manifest。"""
        path = self.policy_dir / self.manifest_filename
        if not path.is_file():
            return
        try:
            manifest = load_manifest(self.policy_dir, self.manifest_filename)
            if not verify_manifest_checksums(manifest, self.policy_dir):
                raise ValueError(boot_t("cjk_gate.policy_manifest_checksum_failed"))
            with self._lock:
                prev = self._manifest
            # 轮询间隔内 manifest 未变化时不写内存、不打 INFO（避免每分钟刷屏）
            if prev is not None and prev.model_dump() == manifest.model_dump():
                return
            with self._lock:
                self._manifest = manifest
            if prev is None:
                logger.info(
                    boot_t(
                        "boot.log.policy_manifest_loaded",
                        version=str(manifest.version),
                        paths=str(list(manifest.prompt_template_paths.keys())),
                    )
                )
            else:
                logger.info(
                    boot_t("boot.log.policy_manifest_hot_reload", version=str(manifest.version))
                )
        except Exception as e:
            with self._lock:
                had = self._manifest is not None
            if had:
                logger.warning(boot_t("boot.log.policy_hot_reload_failed_keep", detail=str(e)))
            else:
                logger.warning(boot_t("boot.log.policy_first_load_failed", detail=str(e)))

    def read_system_templates_from_disk(self) -> str:
        """按 manifest 拼接 system 侧模板（每次从磁盘读取，确保改文件即生效）。"""
        with self._lock:
            m = self._manifest
        if not m or not m.prompt_template_paths:
            return ""
        parts: List[str] = []
        seen = set()
        for key in _SYSTEM_TEMPLATE_KEY_ORDER:
            rel = m.prompt_template_paths.get(key)
            if not rel or rel in seen:
                continue
            seen.add(rel)
            p = (self.policy_dir / rel.replace("\\", "/").lstrip("/")).resolve()
            try:
                if not str(p).startswith(str(self.policy_dir.resolve())):
                    continue
            except OSError:
                continue
            if p.is_file():
                try:
                    parts.append(p.read_text(encoding="utf-8"))
                except OSError as ex:
                    logger.warning(
                        boot_t("boot.log.policy_read_template_failed", path=str(p), detail=str(ex))
                    )
        return "\n\n".join(parts).strip()

    def read_user_fragment_from_disk(self) -> str:
        """可选 user 片段（如任务包装说明）；无则返回空串。"""
        with self._lock:
            m = self._manifest
        if not m:
            return ""
        for key in _USER_TEMPLATE_KEYS:
            rel = m.prompt_template_paths.get(key)
            if not rel:
                continue
            p = (self.policy_dir / rel.replace("\\", "/").lstrip("/")).resolve()
            try:
                if not str(p).startswith(str(self.policy_dir.resolve())):
                    continue
            except OSError:
                continue
            if p.is_file():
                try:
                    return p.read_text(encoding="utf-8").strip()
                except OSError as ex:
                    logger.warning(
                        boot_t(
                            "boot.log.policy_read_user_template_failed",
                            path=str(p),
                            detail=str(ex),
                        )
                    )
        return ""

    async def poll_reload(self) -> None:
        """后台协程：固定间隔 ``reload_interval_sec`` 调用 ``reload_safe``。"""
        while True:
            await asyncio.sleep(self.reload_interval_sec)
            self.reload_safe()

    def try_start_watchdog(self, on_reload: Callable[[], None], *, daemon: bool = True) -> bool:
        """
        若已安装 ``watchdog``，则在后台线程监视 ``manifest.json`` 变更并回调。

        未安装时返回 False，由调用方仅依赖 ``poll_reload`` 即可。
        """
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            logger.debug(boot_t("boot.log.policy_watchdog_not_installed"))
            return False

        manifest_path = (self.policy_dir / self.manifest_filename).resolve()

        class _Handler(FileSystemEventHandler):
            def on_modified(self, event: object) -> None:
                if getattr(event, "is_directory", False):
                    return
                try:
                    src = getattr(event, "src_path", None)
                    if src is None:
                        return
                    if Path(str(src)).resolve() == manifest_path:
                        on_reload()
                except OSError:
                    pass

        obs = Observer()
        if not self.policy_dir.is_dir():
            try:
                self.policy_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                return False
        obs.schedule(_Handler(), str(self.policy_dir), recursive=False)
        obs.daemon = daemon
        obs.start()
        self._watchdog_observer = obs
        logger.info(boot_t("boot.log.policy_watchdog_watching", path=str(self.policy_dir)))
        return True


async def watch_and_reload(
    loader: PolicyLoader,
    *,
    use_watchdog: bool = False,
) -> None:
    """
    统一入口：优先尝试 watchdog（含 manifest 变更回调）+ 仍可与轮询并存。

    当前实现：若 ``use_watchdog`` 且 watchdog 可用，则启动 observer 后**仍**执行
    ``poll_reload``（兜底扫描模板文件变更未触达 manifest mtime 的边缘情况）。
    """
    if use_watchdog:
        loader.try_start_watchdog(loader.reload_safe)
    await loader.poll_reload()
