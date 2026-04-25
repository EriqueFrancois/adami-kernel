# --- START OF FILE skill_validation_result.py ---
"""
AdamI Skill Manager - SkillValidationResult（精细化错误处理数据结构）

用于 SkillValidator / SkillBuilder / Engineer 之间的结构化错误传递。
支持根据 error_type 实现精细化重试策略。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ValidationResult:
    """
    结构化验证结果（工业级错误传递对象）
    """

    passed: bool = True
    errors: List[Dict[str, Any]] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)

    def add_error(self, error_type: str, message: str, line: int = None, suggestion: str = None):
        """便捷添加错误"""
        error_entry = {
            "type": error_type,
            "message": message,
        }
        if line is not None:
            error_entry["line"] = line
        if suggestion:
            error_entry["suggestion"] = suggestion
            self.suggestions.append(suggestion)
        self.errors.append(error_entry)
        self.passed = False

    def __str__(self) -> str:
        if self.passed:
            return "ValidationResult: PASSED"
        return f"ValidationResult: FAILED ({len(self.errors)} errors)\n" + "\n".join(
            f"  • [{e['type']}] {e['message']}" for e in self.errors
        )


# --- END OF FILE skill_validation_result.py ---
