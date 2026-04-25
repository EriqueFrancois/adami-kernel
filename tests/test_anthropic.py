"""历史占位测试：曾假设 `from test_anthropic import execute`，与 pytest 模块名冲突导致无法收集。

若需恢复 Anthropic 技能单测，请将技能实现置于独立包路径并改写 import。
"""

import pytest

pytest.skip(
    "Legacy placeholder: self-import `test_anthropic` breaks pytest collection",
    allow_module_level=True,
)
