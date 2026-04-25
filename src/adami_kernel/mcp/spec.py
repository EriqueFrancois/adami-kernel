from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class McpMountSpec(BaseModel):
    """宿主路径挂载声明（必须命中 allowlist 才会生效）。"""

    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    mode: str = Field(default="ro", pattern=r"^(ro|rw)$")


class McpServerSpec(BaseModel):
    """stdio MCP server 规格（Docker 隔离运行）。"""

    name: str = Field(min_length=1)
    image: str = Field(min_length=1)
    command: List[str] = Field(default_factory=list)
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    workdir: Optional[str] = None
    # 安全增强：默认不挂载宿主路径；若要访问宿主目录需显式声明 mounts + allowlist
    mounts: List[McpMountSpec] = Field(default_factory=list)
    # server 级只读 rootfs 覆盖；None 表示跟随全局 settings.ADAMI_MCP_READ_ONLY_FS
    read_only_fs: Optional[bool] = None
