# src/adami_kernel/core/kernel_context.py
# 文件路径: src/adami_kernel/core/kernel_context.py
# 描述: KernelContext Protocol - DecisionProcessor 所需的最小显式契约（隐式接口 → 显式依赖面）

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, Tuple


class KernelContext(Protocol):
    """DecisionProcessor 所需的最小 Kernel 能力面（显式契约）
    只包含 DecisionProcessor 当前真实访问的字段和方法
    后续重构 LifecycleManager 时可直接实现此 Protocol
    """

    # ====================== 会话与并发控制 ======================
    active_sessions: Dict[str, dict]
    session_locks: Dict[str, Any]

    # ====================== 核心依赖 ======================
    bus: Any
    memory: Any
    router: Any
    toolbox: Any
    immunity: Any
    episodic_memory: Optional[Any]

    # ====================== 规划与路由层 ======================
    planner: Any
    intent_router: Any
    intent_template_registry: Optional[Any]
    skill_router: Any
    evolution_engine: Any
    prompt_builder: Any
    skill_optimizer: Optional[Any]
    second_brain: Optional[Any]

    # ====================== 神经与平台接入 ======================
    telegram_nerve: Optional[Any]
    discord_nerve: Optional[Any]
    proprioception: Optional[Any]

    # ====================== 方法契约（DecisionProcessor 真实调用） ======================
    async def _send_reply(self, chat_id: Any, text: str, platform: str = "telegram") -> None: ...

    async def _handle_system_action(
        self, cmd: str, current_chat_id: Optional[str], platform: str = "telegram"
    ) -> None: ...

    def _parse_decision(self, response: str) -> Tuple[str, dict]: ...

    def _get_current_persona(self) -> str: ...

    # ====================== 可选扩展（未来 DecisionProcessor 可能用到） ======================
    # 保留为空白，方便后续扩展，不影响当前类型检查


# --- END OF FILE src/adami_kernel/core/kernel_context.py ---
# 文件路径: src/adami_kernel/core/kernel_context.py
