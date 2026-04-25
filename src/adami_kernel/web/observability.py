# --- START OF FILE observability.py ---
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from adami_kernel.config import settings
from adami_kernel.web.otel import AdamIOtel

logger = logging.getLogger("AdamI-Observability")


class AdamIObservability:
    """
    AdamI 2.0 深度可观测性工具类（工业级）
    完全复用 Phase 4 已初始化的 AdamIOtel，提供异步 Span 上下文管理器。
    【本次重构】：在技能生成关键环节（生成、验证、写入、加载）增加专用 Span 追踪，记录耗时和结果。
    """

    @staticmethod
    async def is_enabled() -> bool:
        """配置开关检查"""
        return getattr(settings, "ADAMI_ENABLE_OBSERVABILITY", False)

    @asynccontextmanager
    async def start_span(
        self,
        span_name: str,
        workflow_id: Optional[str] = None,
        node_id: Optional[str] = None,
        chat_id: Optional[str] = None,
        node_type: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ):
        """
        异步 Span 上下文管理器
        使用方式：
            async with observability.start_span("workflow.node.execute", workflow_id=..., ...) as span:
                ...
        【新增】当 span_name 包含技能生成关键词时，自动调用专用 Span（生成/验证/写入/加载）
        """
        if not await self.is_enabled():
            # 开关关闭时返回空上下文（零性能开销）
            yield None
            return

        # 构造基础属性
        base_attrs = {
            "workflow_id": workflow_id or "unknown",
            "chat_id": chat_id or "unknown",
        }
        if node_id:
            base_attrs["node_id"] = node_id
        if node_type:
            base_attrs["node_type"] = node_type

        # 合并用户自定义属性
        if attributes:
            base_attrs.update(attributes)

        # 【新增】技能生成关键环节专用 Span 判断
        skill_name = attributes.get("skill_name") if attributes else None
        if skill_name and "generation" in span_name.lower():
            span = AdamIOtel.start_skill_generation_span(skill_name)
        elif skill_name and "validation" in span_name.lower():
            span = AdamIOtel.start_validation_span(skill_name)
        elif skill_name and "write" in span_name.lower():
            span = AdamIOtel.start_write_span(skill_name)
        elif skill_name and "load" in span_name.lower():
            span = AdamIOtel.start_load_span(skill_name)
        else:
            # 通用 Span
            span = AdamIOtel.start_span(name=span_name, attributes=base_attrs)
        # =================================================================================

        try:
            logger.debug(f"[Observability] Span started: {span_name} (workflow={workflow_id})")
            yield span
        finally:
            # 自动结束 Span
            if span:
                span.end()
            logger.debug(f"[Observability] Span ended: {span_name}")


# ====================== 全局单例 ======================
observability = AdamIObservability()
# =================================================================================

# --- END OF FILE observability.py ---
