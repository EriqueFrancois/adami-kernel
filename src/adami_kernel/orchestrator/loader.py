import ast
import importlib.util
import logging
import os
import types
from typing import Optional

from adami_kernel.config import settings
from adami_kernel.i18n import t

logger = logging.getLogger("OrchestratorLoader")


def _orchld_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


def _ast_expr(node: ast.AST) -> str:
    return ast.unparse(node)


class PluginLoader:
    """
    安全的插件热插拔加载器 (深度隔离版)。
    除了内置危险函数，严格拦截系统底层库的导入和属性访问。
    【Bug 4 核心修复】：防止 AST 绕过（os.environ、sys.modules、subprocess.Popen 等）
    【本次强化】：全面拦截动态执行（exec/eval/compile/getattr/setattr）+ 字符串启发式
    【本次重构】：动态技能不再直接执行，全部走 Docker 沙箱（loader 仅负责审计与准备）
    【本次清理】：prepare_for_sandbox 已内联至 evolution.py，本方法已删除（死代码清除）
    """

    # ====================== 强化后的黑名单 ======================
    FORBIDDEN_IMPORTS = {
        "os",
        "sys",
        "subprocess",
        "socket",
        "requests",
        "urllib",
        "shutil",
        "pathlib",
        "ctypes",
        "multiprocessing",
        "builtins",
        "importlib",
    }
    FORBIDDEN_BUILTINS = {
        "eval",
        "exec",
        "open",
        "compile",
        "globals",
        "locals",
        "__import__",
        "getattr",
        "setattr",
        "delattr",
        "execfile",
        "input",
    }
    FORBIDDEN_ATTRS = {
        "system",
        "popen",
        "call",
        "check_output",
        "run",
        "Popen",
        "remove",
        "rmdir",
        "unlink",
        "exec",
        "shell",
        "environ",
        "modules",
        "getattr",
        "setattr",
        "delattr",
        "__getattribute__",
    }
    # ============================================================

    def __init__(self, safe_dir: Optional[str] = None) -> None:
        self.safe_dir = safe_dir if safe_dir is not None else settings.path_plugins_safe_dir
        os.makedirs(self.safe_dir, exist_ok=True)

    def audit_code(self, source_code: str) -> bool:
        """AST 静态合规审计 + 强化动态执行拦截 + 字符串危险模式"""
        try:
            tree = ast.parse(source_code)
            for node in ast.walk(tree):
                # === Import 检查（原有 + 强化）===
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        base = alias.name.split(".")[0]
                        if base in self.FORBIDDEN_IMPORTS:
                            logger.error(_orchld_t("orchld.err.imp", nm=alias.name))
                            return False
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.module.split(".")[0] in self.FORBIDDEN_IMPORTS:
                        logger.error(_orchld_t("orchld.err.imp_from", mod=node.module))
                        return False

                # === Attribute 访问（os.environ、sys.modules 等）===
                elif isinstance(node, ast.Attribute):
                    leftmost = node
                    while isinstance(leftmost, ast.Attribute):
                        leftmost = leftmost.value
                    if isinstance(leftmost, ast.Name) and leftmost.id in self.FORBIDDEN_IMPORTS:
                        logger.error(_orchld_t("orchld.err.attr", expr=_ast_expr(node)))
                        return False

                # === Call 检查（强化：exec/eval/compile/getattr/setattr 等）===
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        if node.func.id in self.FORBIDDEN_BUILTINS:
                            logger.error(_orchld_t("orchld.err.builtin", fn=node.func.id))
                            return False
                    elif isinstance(node.func, ast.Attribute):
                        if node.func.attr in self.FORBIDDEN_ATTRS:
                            logger.error(_orchld_t("orchld.err.method", attr=node.func.attr))
                            return False
                        # 递归检查最左端模块
                        leftmost = node.func
                        while isinstance(leftmost, ast.Attribute):
                            leftmost = leftmost.value
                        if isinstance(leftmost, ast.Name) and leftmost.id in self.FORBIDDEN_IMPORTS:
                            logger.error(
                                _orchld_t("orchld.err.mod_call", expr=_ast_expr(node.func))
                            )
                            return False

                # === 字符串常量启发式扫描（强化版）===
                elif isinstance(node, (ast.Str, ast.Constant)) and isinstance(
                    getattr(node, "value", None), str
                ):
                    dangerous_str = node.value.lower()
                    dangerous_patterns = [
                        "os.system",
                        "subprocess",
                        "shell=true",
                        "rm -rf",
                        "__import__",
                        "eval(",
                        "exec(",
                        "compile(",
                        "getattr(",
                        "setattr(",
                        "delattr(",
                        "popen(",
                        "call(",
                        "check_output(",
                        "run(",
                        "system(",
                    ]
                    if any(kw in dangerous_str for kw in dangerous_patterns):
                        logger.error(_orchld_t("orchld.err.str_pat", snippet=node.value[:120]))
                        return False

            logger.info(_orchld_t("orchld.log.audit_ok"))
            return True

        except SyntaxError as e:
            logger.error(_orchld_t("orchld.err.syntax", e=e))
            return False

    def load_plugin(self, plugin_name: str, file_path: str) -> Optional[types.ModuleType]:
        """重构后：不再直接执行，仅返回规格（供 Docker 沙箱使用）"""
        if not os.path.exists(file_path):
            return None

        with open(file_path, "r", encoding="utf-8") as f:
            source_code = f.read()

        if not self.audit_code(source_code):
            logger.critical(_orchld_t("orchld.critical.audit_fail", nm=plugin_name))
            return None

        try:
            spec = importlib.util.spec_from_file_location(plugin_name, file_path)
            if spec is None or spec.loader is None:
                return None
            logger.info(_orchld_t("orchld.log.prepare_ok", nm=plugin_name))
            return spec  # 返回 spec 而非已加载 module
        except Exception as e:
            logger.error(_orchld_t("orchld.err.prepare", nm=plugin_name, e=e))
            return None

    # ====================== 【本次新增】initialize 方法（修复 kernel 调用） ======================
    async def initialize(self):
        """沙箱加载器初始化（kernel boot 时调用）"""
        # 确保 sandbox_volume 目录存在
        sandbox_volume = settings.path_sandbox_volume_dir
        os.makedirs(sandbox_volume, exist_ok=True)
        logger.info(_orchld_t("orchld.log.sandbox_init"))

    # =================================================================================
