import asyncio
import hashlib
import os


class FileSystemTool:
    def __init__(self, sandbox_dir: str):
        self.sandbox_dir = os.path.abspath(sandbox_dir)

    def _safe_path(self, file_path: str) -> str:
        """[SECURITY PATCH] 沙箱安全路径控制 (防 Symlink 穿透版)"""
        target_path = os.path.abspath(os.path.join(self.sandbox_dir, file_path))
        # 获取解析软链接后的真实绝对物理路径
        real_path = os.path.realpath(target_path)
        if not real_path.startswith(self.sandbox_dir):
            raise PermissionError(
                f"Immune System: Path traversal or Symlink escape detected! ({file_path})"
            )
        return real_path

    async def list_directory(self, path: str = ".") -> str:
        safe_path = self._safe_path(path)
        if not os.path.exists(safe_path) or not os.path.isdir(safe_path):
            return "Error: Directory not found."

        def _list():
            return "\n".join(os.listdir(safe_path))

        return await asyncio.to_thread(_list)

    async def calculate_md5(self, file_path: str) -> str:
        """新加入的 MD5 计算本能"""
        safe_path = self._safe_path(file_path)
        if not os.path.exists(safe_path) or not os.path.isfile(safe_path):
            return "Error: File not found."

        def _hash():
            hasher = hashlib.md5()
            with open(safe_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()

        return await asyncio.to_thread(_hash)
