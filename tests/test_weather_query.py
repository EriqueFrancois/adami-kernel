"""历史天气技能测试文件曾混入 Markdown，无法解析。

当前仓库无稳定的 `src.skills.weather_query` 包路径；需要时用 `pytest.importorskip` 与真实技能路径重写。
"""

import pytest

pytest.skip(
    "Legacy file corrupted / wrong import path (src.skills.weather_query)",
    allow_module_level=True,
)
