from typing import Any, Dict, List, Optional

from adami_kernel.config import settings
from adami_kernel.i18n import t as i18n_t

# ==================== 智能搜索后端切换（优先 ddgs，fallback duckduckgo_search） ====================
# 注意：单测/最小运行环境可能两者都不存在，此时降级为“不可用后端”，search() 会返回可读错误。
try:
    from ddgs import DDGS  # type: ignore

    SEARCH_BACKEND = "ddgs"
except ImportError:
    try:
        from duckduckgo_search import DDGS  # type: ignore

        SEARCH_BACKEND = "duckduckgo_search"
    except ImportError:
        DDGS = None  # type: ignore[assignment]
        SEARCH_BACKEND = "unavailable"


def _webt_t(key: str, **kwargs: object) -> str:
    return i18n_t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class WebTool:
    """智能网页搜索工具（自动适配 Mac / AWS）"""

    def __init__(self, sandbox_dir: str):
        self.sandbox_dir = sandbox_dir
        # 可在此添加其他初始化逻辑

    async def search(
        self,
        query: str,
        max_results: int = 5,
        *,
        timelimit: Optional[str] = None,
        region: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """统一搜索接口。

        timelimit: 传给 DDGS 的时间窗（如 ``d``/``w``/``m``/``y``），用于简报等场景收紧新闻时效。
        region: 传给 DDGS 的区域偏好（如 ``us-en``、``zh-cn``），减轻非目标语种结果占比。
        """
        try:
            if DDGS is None:
                return [
                    {
                        "title": _webt_t("webt.err.backend_title"),
                        "href": "",
                        "body": _webt_t("webt.err.backend_body"),
                    }
                ]
            with DDGS() as ddgs:
                kwargs: Dict[str, Any] = {"max_results": max_results}
                if timelimit:
                    kwargs["timelimit"] = timelimit
                if region:
                    kwargs["region"] = region
                results = ddgs.text(query, **kwargs)
                return [
                    {
                        "title": r.get("title", ""),
                        "href": r.get("href", ""),
                        "body": r.get("body", ""),
                    }
                    for r in results
                ]
        except Exception as e:
            return [
                {
                    "title": _webt_t("webt.err.fail_title"),
                    "href": "",
                    "body": _webt_t("webt.err.fail_body", detail=str(e), backend=SEARCH_BACKEND),
                }
            ]

    # 保留其他原有方法（如果你的原始版本有额外方法，可在此补充）
