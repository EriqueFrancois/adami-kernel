"""Agent↔Tool 契约层：统一 tool_id、schema 与 LLM 文本块，供 Planner / MCP / 外部工具共用。

tool_id 约定：与现有 MCP 映射一致，形如 ``MCP.<server>.<tool>``（大写）；内置工具为历史大写名（如 ``WEB_SEARCH``）。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Literal, Optional, Sequence

from pydantic import BaseModel, Field, field_validator

from adami_kernel.config import settings
from adami_kernel.i18n import t as i18n_t

ToolSource = Literal["native", "mcp", "external"]
RiskTier = Literal["low", "medium", "high"]


def _mcpf_t(key: str, **kwargs: Any) -> str:
    return i18n_t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class ToolCapability(BaseModel):
    """契约层工具能力描述（Planner/Executor 只认 tool_id）。"""

    tool_id: str
    source: ToolSource = "native"
    mcp_server: Optional[str] = None
    mcp_tool_name: Optional[str] = None
    json_schema: Dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    risk_tier: RiskTier = "medium"
    requires_approval: bool = False
    exposed: bool = True

    @field_validator("tool_id")
    @classmethod
    def _upper_id(cls, v: str) -> str:
        return (v or "").strip().upper()


class ToolInvocation(BaseModel):
    tool_id: str
    args: Dict[str, Any] = Field(default_factory=dict)
    trace_id: str = ""
    chat_id: str = ""

    @field_validator("tool_id")
    @classmethod
    def _upper_id(cls, v: str) -> str:
        return (v or "").strip().upper()


class ToolResult(BaseModel):
    structured: Optional[Any] = None
    text: str = ""
    error_code: Optional[str] = None


class ToolContractRegistry:
    """按 tool_id 索引的契约注册表；与 EvolutionEngine.tool_schemas 同步写入，避免长期双写分裂。"""

    def __init__(self) -> None:
        self._caps: Dict[str, ToolCapability] = {}

    def register(self, cap: ToolCapability) -> None:
        self._caps[cap.tool_id.upper()] = cap

    def unregister(self, tool_id: str) -> None:
        self._caps.pop(tool_id.upper().strip(), None)

    def get(self, tool_id: str) -> Optional[ToolCapability]:
        return self._caps.get(tool_id.upper().strip())

    def clear_source(self, source: ToolSource) -> int:
        to_del = [k for k, v in self._caps.items() if v.source == source]
        for k in to_del:
            del self._caps[k]
        return len(to_del)

    def list_exposed(self) -> List[ToolCapability]:
        return [c for c in self._caps.values() if c.exposed]

    def list_exposed_sorted(self) -> List[ToolCapability]:
        return sorted(self.list_exposed(), key=lambda c: c.tool_id)

    def __len__(self) -> int:
        return len(self._caps)


def tool_capability_native(
    tool_id: str,
    json_schema: Dict[str, Any],
    description: str = "",
    *,
    risk_tier: RiskTier = "medium",
    requires_approval: bool = False,
    exposed: bool = True,
) -> ToolCapability:
    return ToolCapability(
        tool_id=tool_id.upper(),
        source="native",
        json_schema=json_schema,
        description=description,
        risk_tier=risk_tier,
        requires_approval=requires_approval,
        exposed=exposed,
    )


def tool_capability_mcp(
    adami_tool_id: str,
    json_schema: Dict[str, Any],
    description: str,
    mcp_server: str,
    mcp_tool_name: str,
    *,
    risk_tier: RiskTier = "medium",
    requires_approval: bool = False,
    exposed: bool = True,
) -> ToolCapability:
    return ToolCapability(
        tool_id=adami_tool_id.upper(),
        source="mcp",
        mcp_server=mcp_server,
        mcp_tool_name=mcp_tool_name,
        json_schema=json_schema,
        description=description,
        risk_tier=risk_tier,
        requires_approval=requires_approval,
        exposed=exposed,
    )


def tool_capability_external(
    tool_id: str,
    json_schema: Dict[str, Any],
    description: str = "",
    *,
    risk_tier: RiskTier = "medium",
    requires_approval: bool = False,
    exposed: bool = True,
) -> ToolCapability:
    """仅通过 ToolboxManager 注册、未走 EvolutionEngine 的外部工具。"""
    return ToolCapability(
        tool_id=tool_id.upper(),
        source="external",
        json_schema=json_schema,
        description=description,
        risk_tier=risk_tier,
        requires_approval=requires_approval,
        exposed=exposed,
    )


def to_llm_prompt_fragment(
    capabilities: Sequence[ToolCapability],
    *,
    max_chars: Optional[int] = None,
) -> str:
    """生成与 ``EvolutionEngine.get_registered_tools_for_llm`` 相同风格的文本块（2.1 兼容）。"""
    caps = [c for c in capabilities if c.exposed]
    if not caps:
        return ""
    lines = [_mcpf_t("mcpf.header")]
    for cap in sorted(caps, key=lambda x: x.tool_id):
        schema_str = json.dumps(cap.json_schema, ensure_ascii=False, indent=2)
        lines.append(
            _mcpf_t(
                "mcpf.block",
                tool_id=cap.tool_id,
                description=cap.description,
                schema_str=schema_str,
            )
        )
    out = "\n".join(lines) + _mcpf_t("mcpf.footer")
    if max_chars is not None and len(out) > max_chars:
        return out[:max_chars] + _mcpf_t("mcpf.truncated")
    return out


def legacy_fragment_from_tool_schemas(tool_schemas: Dict[str, Dict[str, Any]]) -> str:
    """从 ``tool_schemas`` 字典生成与历史一致的 LLM 块（无契约注册表时的回退）。"""
    if not tool_schemas:
        return ""
    caps: List[ToolCapability] = []
    for name, info in tool_schemas.items():
        caps.append(
            ToolCapability(
                tool_id=name.upper(),
                source="native",
                json_schema=info.get("json_schema", {}) or {},
                description=str(info.get("description", "")),
                exposed=True,
            )
        )
    return to_llm_prompt_fragment(caps)
