"""Agent Lightning 可选依赖探测与惰性符号导出。

内核其它模块只应 import 本模块的 ``AGL_AVAILABLE`` / ``agl``，避免硬依赖 agentlightning。
"""

from __future__ import annotations

from typing import Any, Optional


def _init_agl() -> tuple[bool, Optional[Any], Optional[BaseException]]:
    try:
        import agentlightning as _agl

        return True, _agl, None
    except BaseException as exc:  # pragma: no cover - import guard
        return False, None, exc


AGL_AVAILABLE, agl, IMPORT_ERROR = _init_agl()
