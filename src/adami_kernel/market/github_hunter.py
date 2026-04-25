# src/adami_kernel/market/github_hunter.py
# GitHubHunter - Tier 1 高星代码猎手（最终生产加强版 + Step 4 强力执行回退降级）

import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import httpx

from adami_kernel.config import settings
from adami_kernel.cortex.router import LLMRouter
from adami_kernel.i18n import t
from adami_kernel.i18n.boot_msg import boot_t
from adami_kernel.market.prompt_constants import GITHUB_KEYWORD_REFINE

logger = logging.getLogger("AdamI-GitHubHunter")


def _gh_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class GitHubHunter:
    """
    AdamI GitHub 代码猎手（第三阶段 Tier 1 最终生产版 + Step 4 强力执行回退降级）
    【第三阶段最终修正】：关键词提炼大幅强化 + 新增仓库相关性过滤 + 空查询硬兜底
    【Step 4 新增】：httpx 客户端 1.0s 硬超时 + GracefulDegrade 日志（配合 SkillFactory 1秒整体掐断），
                 确保 GitHub Tier 1 绝不卡住整个工作流，用时间换成功率
    """

    def __init__(self, router: LLMRouter):
        self.router = router
        self.token = settings.GITHUB_TOKEN
        self.headers = {"Accept": "application/vnd.github.v3+json"}
        if self.token:
            self.headers["Authorization"] = f"token {self.token}"
            logger.info(boot_t("boot.log.github_token"))
        else:
            logger.warning(boot_t("boot.log.github_no_token"))

        # ====================== 【Step 4 强力执行回退降级】 ======================
        self.client = httpx.AsyncClient(timeout=1.0, headers=self.headers)
        logger.info(boot_t("boot.log.github_timeout", seconds=1.0))
        # =====================================================================

        logger.info(boot_t("boot.log.github_search_live"))
        logger.info(boot_t("boot.log.github_min_stars", stars=settings.ADAMI_GITHUB_MIN_STARS))

    # ====================== 智能 URL 解析 ======================
    def _extract_repo_full_name(self, repo_url: str) -> str:
        """从 GitHub URL 中提取 'owner/repo' 格式的仓库全名"""
        if re.match(r"^[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+$", repo_url):
            return repo_url
        match = re.search(r"github\.com/([^/]+)/([^/]+)", repo_url)
        if match:
            return f"{match.group(1)}/{match.group(2)}"
        raise ValueError(boot_t("cjk_gate.github_url_parse_error", url=repo_url))

    # ====================== Tier 1 核心搜索接口 ======================
    async def search_and_extract(
        self, query: str, min_stars: Optional[int] = None, language: str = "python", limit: int = 3
    ) -> Optional[str]:
        effective_min_stars = (
            min_stars if min_stars is not None else settings.ADAMI_GITHUB_MIN_STARS
        )

        logger.info(
            _gh_t(
                "ghht.log.tier1_start",
                snippet=query[:100],
                ms=effective_min_stars,
                lang=language,
            )
        )

        refined_query = await self._refine_search_keyword(query)
        logger.info(_gh_t("ghht.log.refine", oldlen=len(query), q=refined_query))

        if not refined_query.strip():
            refined_query = "api python httpx async"
            logger.warning(_gh_t("ghht.warn.refine_empty"))

        repos = await self.search_repos(
            query=refined_query, min_stars=effective_min_stars, language=language, limit=limit
        )
        if not repos:
            logger.warning(_gh_t("ghht.warn.tier1_none"))
            return None

        # 新增：仓库相关性过滤
        best_repo = self._filter_relevant_repo(repos, query)
        logger.info(
            _gh_t(
                "ghht.log.repo_pick",
                repo=best_repo["full_name"],
                stars=best_repo["stars"],
            )
        )

        code = await self.fetch_code(best_repo["html_url"])
        if not code:
            logger.warning(_gh_t("ghht.warn.fetch_empty", repo=best_repo["full_name"]))
            return None

        logger.info(_gh_t("ghht.log.code_ok", n=len(code)))
        return code

    # ====================== 本地LLM关键词提炼（最终加强版） ======================
    async def _refine_search_keyword(self, original_query: str) -> str:
        prompt = GITHUB_KEYWORD_REFINE.format(original_query=original_query[:500])
        try:
            response = await self.router.call_llm(
                prompt, brain_type="think", temperature=0.0, max_tokens=80
            )
            refined = response.strip()
            if not refined or len(refined) > 120:
                return "api python httpx async"
            return refined
        except Exception as e:
            logger.warning(_gh_t("ghht.warn.refine_llm", e=e))
            return "api python httpx async"

    # ====================== 新增：仓库相关性过滤 ======================
    def _filter_relevant_repo(self, repos: List[Dict], original_query: str) -> Dict:
        """优先选择与 weather / api 相关的仓库"""
        keywords = ["weather", "api", "httpx", "async", "climate", "forecast"]
        for repo in repos:
            name = (repo.get("full_name", "") + " " + repo.get("description", "")).lower()
            if any(k in name for k in keywords):
                return repo
        return repos[0]  # 兜底返回最高星

    # ====================== 以下方法 100% 保留（完整未删减） ======================
    async def search_repos(
        self,
        query: str,
        category: Optional[str] = None,
        min_stars: int = 0,
        language: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict]:
        logger.info(
            _gh_t(
                "ghht.log.search",
                q=query,
                ms=min_stars,
                lang=language,
                lim=limit,
            )
        )

        full_query = query.strip()
        if category:
            full_query += f" topic:{category}"
        if min_stars > 0:
            full_query += f" stars:>={min_stars}"
        if language:
            full_query += f" language:{language}"
        two_years_ago = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
        full_query += f" pushed:>{two_years_ago}"

        url = "https://api.github.com/search/repositories"
        params = {"q": full_query, "sort": "stars", "order": "desc", "per_page": limit}

        try:
            resp = await self.client.get(url, params=params)
            logger.info(_gh_t("ghht.log.api_status", code=resp.status_code))

            if resp.status_code == 403:
                logger.error(_gh_t("ghht.err.rate_limit"))
                return []

            resp.raise_for_status()
            data = resp.json()

            repos = []
            for item in data.get("items", []):
                repos.append(
                    {
                        "name": item["name"],
                        "full_name": item["full_name"],
                        "html_url": item["html_url"],
                        "description": item.get("description")
                        or _gh_t("market.list.no_description"),
                        "stars": item["stargazers_count"],
                        "forks": item["forks_count"],
                        "language": item.get("language"),
                        "updated_at": item.get("updated_at"),
                        "score": round(
                            item["stargazers_count"] * 0.7 + item["forks_count"] * 0.3, 2
                        ),
                    }
                )

            repos.sort(key=lambda x: x["stars"], reverse=True)
            logger.info(_gh_t("ghht.log.repos_n", n=len(repos)))
            return repos

        except httpx.HTTPStatusError as e:
            logger.error(
                _gh_t(
                    "ghht.err.api_http",
                    code=e.response.status_code,
                    body=e.response.text,
                )
            )
            return []
        except Exception as e:
            logger.error(_gh_t("ghht.err.search_exc", e=e))
            return []

    async def fetch_code(self, repo_url: str, path: str = "", max_depth: int = 2) -> Optional[str]:
        try:
            repo_full_name = self._extract_repo_full_name(repo_url)
            return await self._search_py_file(repo_full_name, path, max_depth, current_depth=0)
        except Exception as e:
            logger.error(_gh_t("ghht.err.fetch_repo", url=repo_url, e=e))
            return None

    async def _search_py_file(
        self, repo_full_name: str, path: str, max_depth: int, current_depth: int
    ) -> Optional[str]:
        if current_depth >= max_depth:
            logger.debug(
                _gh_t(
                    "ghht.debug.max_depth",
                    d=max_depth,
                    repo=repo_full_name,
                    path=path,
                )
            )
            return None

        url = f"https://api.github.com/repos/{repo_full_name}/contents/{path}"
        try:
            resp = await self.client.get(url)
            if resp.status_code != 200:
                logger.warning(
                    _gh_t(
                        "ghht.warn.path_http",
                        repo=repo_full_name,
                        path=path,
                        code=resp.status_code,
                    )
                )
                return None
            data = resp.json()

            if isinstance(data, dict) and data.get("type") == "file":
                if data["name"].endswith(".py"):
                    return await self._download_file(data["download_url"])
                return None

            if isinstance(data, list):
                for item in data:
                    if item["type"] == "file" and item["name"].endswith(".py"):
                        return await self._download_file(item["download_url"])
                for item in data:
                    if item["type"] == "dir":
                        result = await self._search_py_file(
                            repo_full_name, item["path"], max_depth, current_depth + 1
                        )
                        if result:
                            return result
                return None

            return None

        except httpx.HTTPStatusError as e:
            logger.error(_gh_t("ghht.err.api_url", code=e.response.status_code, url=url))
            return None
        except Exception as e:
            logger.error(_gh_t("ghht.err.tree_exc", repo=repo_full_name, path=path, e=e))
            return None

    async def _download_file(self, download_url: str) -> Optional[str]:
        try:
            resp = await self.client.get(download_url)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            logger.error(_gh_t("ghht.err.download", e=e))
            return None

    async def close(self):
        await self.client.aclose()


# --- END OF FILE github_hunter.py ---
