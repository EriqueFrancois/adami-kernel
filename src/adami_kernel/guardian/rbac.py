import logging
from typing import Dict, List, Set

logger = logging.getLogger("GuardianRBAC")


class RBACMatrix:
    """
    动态角色访问控制矩阵。
    支持从配置字典中批量加载权限映射。
    """

    def __init__(self) -> None:
        # module_name -> set of allowed topics
        self._permissions: Dict[str, Set[str]] = {}

    def grant(self, module: str, topic: str) -> None:
        """授予模块对特定主题的发布/订阅权限"""
        if module not in self._permissions:
            self._permissions[module] = set()
        self._permissions[module].add(topic)
        logger.info(f"[RBAC] Granted: '{module}' -> '{topic}'")

    def revoke(self, module: str, topic: str) -> None:
        """撤销模块对特定主题的权限"""
        if module in self._permissions and topic in self._permissions[module]:
            self._permissions[module].remove(topic)
            logger.warning(f"[RBAC] Revoked: '{module}' -> '{topic}'")

    def check(self, module: str, topic: str) -> bool:
        """鉴权：检查模块是否拥有该主题的权限"""
        has_permission = module in self._permissions and topic in self._permissions[module]
        if not has_permission:
            logger.error(
                f"[RBAC DENY] Module '{module}' attempted unauthorized access to '{topic}'"
            )
        return has_permission

    def load_from_dict(self, config: Dict[str, List[str]]) -> None:
        """从字典动态加载权限矩阵"""
        for module, topics in config.items():
            for topic in topics:
                self.grant(module, topic)
        logger.info("[RBAC] Matrix successfully loaded from configuration.")
