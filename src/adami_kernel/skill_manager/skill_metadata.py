# --- START OF FILE skill_metadata.py ---
"""
技能元数据模型，用于管理技能的版本、评分、调用统计等信息。
存储在 LayeredMemory 的 skill_metadata 域中。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from adami_kernel.config import settings
from adami_kernel.i18n import t as i18n_t


def _smeta_d(key: str) -> str:
    return i18n_t(key, locale=settings.effective_ui_default_locale())


class SkillVersion(BaseModel):
    """单个技能版本的信息"""

    version: str = Field(..., description=_smeta_d("smeta.field.version"))
    code: str = Field(..., description=_smeta_d("smeta.field.code"))
    score: float = Field(default=100.0, description=_smeta_d("smeta.field.score_ver"))
    reason: Optional[str] = Field(default=None, description=_smeta_d("smeta.field.reason"))
    created_at: datetime = Field(
        default_factory=datetime.now, description=_smeta_d("smeta.field.created_ver")
    )


class SkillMetadata(BaseModel):
    """
    技能的完整元数据，支持版本管理、动态评分和状态机。
    每个技能对应一条记录，存储在 LayeredMemory 中。
    """

    skill_name: str = Field(..., description=_smeta_d("smeta.field.skill_name"))
    status: str = Field(default="active", description=_smeta_d("smeta.field.status"))
    current_version: str = Field(..., description=_smeta_d("smeta.field.current_version"))
    score: float = Field(default=100.0, description=_smeta_d("smeta.field.score_meta"))
    metrics: Dict[str, Any] = Field(
        default_factory=lambda: {
            "total_calls": 0,
            "success_calls": 0,
            "consecutive_failures": 0,
            "last_used": None,
            "last_error": None,
        },
        description=_smeta_d("smeta.field.metrics"),
    )
    versions: Dict[str, SkillVersion] = Field(
        default_factory=dict,
        description=_smeta_d("smeta.field.versions"),
    )
    created_at: datetime = Field(
        default_factory=datetime.now, description=_smeta_d("smeta.field.created_meta")
    )
    updated_at: datetime = Field(
        default_factory=datetime.now, description=_smeta_d("smeta.field.updated_meta")
    )
    # Anthropic / SkillRouter 轻量字段（可选；LayeredMemory 中的记录通常不含这些）
    description: Optional[str] = Field(default=None, description="技能简述，用于路由与向量检索")
    prompt_template: Optional[str] = Field(
        default=None, description="Anthropic SKILL.md 正文或注入提示模板"
    )
    required_params: List[str] = Field(default_factory=list, description="模板中的占位参数名")
    category: Optional[str] = Field(default=None, description="分类标签")
    tags: List[str] = Field(default_factory=list, description="检索用标签")
    source: Optional[str] = Field(default=None, description="来源，如 anthropic-official")
    extra_metadata: Dict[str, Any] = Field(
        default_factory=dict, description="SKILL.md frontmatter 原始扩展字段"
    )

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}
        extra = "ignore"  # 允许未来扩展字段

    def update_score(self, success: bool, error: Optional[str] = None) -> None:
        """
        根据执行结果更新评分。
        成功：score = min(100, score * 0.9 + 10)  # 平滑递增
        失败：score = max(0, score - 20)  # 快速降级
        """
        if success:
            self.score = min(100.0, self.score * 0.9 + 10.0)
            self.metrics["success_calls"] += 1
            self.metrics["consecutive_failures"] = 0
        else:
            self.score = max(0.0, self.score - 20.0)
            self.metrics["consecutive_failures"] += 1
            self.metrics["last_error"] = error

        self.metrics["total_calls"] += 1
        self.metrics["last_used"] = datetime.now().isoformat()

        # 状态机转换
        if self.score < 60 or self.metrics["consecutive_failures"] >= 3:
            self.status = "needs_optimization"
        elif self.score >= 80:
            self.status = "active"

        self.updated_at = datetime.now()

    def add_version(self, version: str, code: str, reason: Optional[str] = None) -> None:
        """添加新版本，并自动设置为当前版本"""
        self.versions[version] = SkillVersion(
            version=version, code=code, reason=reason, created_at=datetime.now()
        )
        self.current_version = version
        self.updated_at = datetime.now()

    def get_current_code(self) -> str:
        """获取当前版本的代码"""
        return self.versions[self.current_version].code


# ====================== 序列化辅助函数 ======================
def serialize_skill_metadata(metadata: SkillMetadata) -> Dict[str, Any]:
    """
    将 SkillMetadata 对象转换为 JSON 可序列化的字典。
    将所有 datetime 对象转换为 ISO 格式字符串。
    """
    payload = metadata.model_dump()
    if "created_at" in payload and hasattr(payload["created_at"], "isoformat"):
        payload["created_at"] = payload["created_at"].isoformat()
    if "updated_at" in payload and hasattr(payload["updated_at"], "isoformat"):
        payload["updated_at"] = payload["updated_at"].isoformat()
    if "versions" in payload:
        for ver in payload["versions"].values():
            if "created_at" in ver and hasattr(ver["created_at"], "isoformat"):
                ver["created_at"] = ver["created_at"].isoformat()
    return payload
