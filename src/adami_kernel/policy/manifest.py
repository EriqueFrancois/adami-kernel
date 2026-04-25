# src/adami_kernel/policy/manifest.py
"""策略包 manifest 契约（训练侧导出 / 推理侧热加载）。"""

from __future__ import annotations

from typing import Dict, Optional

from pydantic import BaseModel, Field


class PolicyManifest(BaseModel):
    """
    policy 目录根下的 manifest.json 结构。

    - ``prompt_template_paths``: 逻辑名 → 相对 ``ADAMI_POLICY_DIR`` 的模板路径。
    - ``checksums``: 相对路径 → 文件内容 SHA256（hex）；用于校验是否被篡改。
    - ``optional_model_ref``: 可选，训练/导出时记录的推荐模型 ID（推理侧仅作元数据）。
    """

    version: str = "0.0.0"
    prompt_template_paths: Dict[str, str] = Field(default_factory=dict)
    checksums: Dict[str, str] = Field(default_factory=dict)
    optional_model_ref: Optional[str] = None
