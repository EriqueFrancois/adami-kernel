# src/adami_kernel/web/market_routes.py
# 文件路径: src/adami_kernel/web/market_routes.py
# 描述: Skill Market API 路由，使用 FastAPI app.state 依赖注入模式（无全局变量）

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from adami_kernel.config import settings
from adami_kernel.i18n import t
from adami_kernel.i18n.boot_msg import boot_t

logger = logging.getLogger("AdamI-MarketRoutes")


def _mr_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


# ====================== Pydantic Models ======================
class SkillResponse(BaseModel):
    name: str
    type: str
    status: str
    source: str
    installed_at: Optional[str] = None
    description: Optional[str] = None
    stars: Optional[int] = None


class InstallRequest(BaseModel):
    skill_name: str
    source: str = "local"
    repo_url: Optional[str] = None


class UploadSkillRequest(BaseModel):
    skill_name: str
    description: str = ""
    code: str


class InstallResponse(BaseModel):
    status: str
    message: str
    skill_name: str
    melted: bool


class Recommendation(BaseModel):
    skill_name: str
    title: str
    confidence: float
    reason: str
    category: str
    repo_url: Optional[str] = None


class GitHubRepo(BaseModel):
    name: str
    full_name: str
    html_url: str
    description: Optional[str]
    stars: int
    forks: int
    language: Optional[str]
    score: float
    installed: bool = False


class DeleteResponse(BaseModel):
    status: str
    message: str


class MarketHealth(BaseModel):
    status: str = "healthy"
    service: str = "SkillMarket"
    github_hunter: str = "disabled"
    total_skills: int = 0


# ====================== Router ======================
router = APIRouter(prefix="/market", tags=["Skill Market"])


# ====================== Dependency Getters (app.state 注入) ======================
def _get_market(request: Request):
    """从 FastAPI app.state 获取 SkillMarket 实例"""
    market = getattr(request.app.state, "skill_market", None)
    if market is None:
        logger.warning(_mr_t("mktw.warn.no_market"))
        raise HTTPException(status_code=503, detail=_mr_t("market.api.skillmarket_not_initialized"))
    return market


def _get_hunter(request: Request):
    """从 FastAPI app.state 获取 GitHubHunter 实例"""
    hunter = getattr(request.app.state, "github_hunter", None)
    if hunter is None:
        logger.warning(_mr_t("mktw.warn.no_hunter"))
        raise HTTPException(status_code=503, detail=_mr_t("market.api.github_not_initialized"))
    return hunter


# ====================== 端点 ======================
@router.get("/skills", response_model=List[SkillResponse])
async def get_skills(request: Request):
    """返回所有技能 + 统一总数（前端 Market.tsx / App.tsx 调用）"""
    skill_market = _get_market(request)
    try:
        skills = await skill_market.list_all_skills()
        total = len(skills)
        if hasattr(skill_market, "_total_count"):
            skill_market._total_count = total
        logger.debug(_mr_t("mktw.debug.list_n", n=total))
        return skills
    except Exception as e:
        logger.error(_mr_t("mktw.err.get_skills", e=e))
        raise HTTPException(status_code=500, detail=_mr_t("market.api.list_skills_failed")) from e


@router.get("/recommend", response_model=List[Recommendation])
async def get_recommendations(request: Request, limit: int = Query(6, ge=1, le=12)):
    skill_market = _get_market(request)
    try:
        return await skill_market.get_recommendations(limit)
    except Exception as e:
        logger.error(_mr_t("mktw.err.recommend", e=e))
        raise HTTPException(status_code=500, detail=_mr_t("market.api.recommend_failed")) from e


@router.get("/search")
async def search_github(request: Request, q: str = Query(..., min_length=2)):
    """GitHub 猎手搜索（实时安装状态）"""
    github_hunter = _get_hunter(request)
    try:
        logger.info(_mr_t("mktw.log.gh_search", q=q))
        results = await github_hunter.search_repos(q)

        # 每次搜索都强制拉取最新安装状态（market 可选）
        installed_set = set()
        try:
            skill_market = getattr(request.app.state, "skill_market", None)
            if skill_market:
                all_skills = await skill_market.list_all_skills()
                installed_set = {s["name"].upper() for s in all_skills}
                logger.info(_mr_t("mktw.log.gh_installed_n", n=len(installed_set)))
        except Exception as status_err:
            logger.warning(_mr_t("mktw.warn.installed_status", e=status_err))

        for repo in results:
            repo["installed"] = repo["name"].upper() in installed_set

        logger.info(_mr_t("mktw.log.gh_done", n=len(results)))
        return results
    except Exception as e:
        logger.error(_mr_t("mktw.err.gh_search", e=e), exc_info=True)
        raise HTTPException(status_code=500, detail=_mr_t("market.api.github_search_failed")) from e


@router.post("/install", response_model=InstallResponse)
async def install_skill(request: Request, body: InstallRequest):
    skill_market = _get_market(request)
    try:
        result = await skill_market.install_skill(body.skill_name, body.source, body.repo_url)
        if result.get("status") == "success":
            return {
                "status": "success",
                "message": result.get("message", _mr_t("market.api.install_ok")),
                "skill_name": body.skill_name,
                "melted": True,
            }
        else:
            return {
                "status": "error",
                "message": result.get("error", _mr_t("market.api.install_failed")),
                "skill_name": body.skill_name,
                "melted": False,
            }
    except Exception as e:
        logger.error(_mr_t("mktw.err.install", e=e))
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/upload", response_model=InstallResponse)
async def upload_custom_skill(request: Request, body: UploadSkillRequest):
    skill_market = _get_market(request)
    try:
        result = await skill_market.upload_custom_skill(
            skill_name=body.skill_name, description=body.description, code=body.code
        )
        if result.get("status") == "success":
            return result
        else:
            return {
                "status": "error",
                "message": result.get("error", _mr_t("market.api.upload_failed")),
                "skill_name": body.skill_name,
                "melted": False,
            }
    except Exception as e:
        logger.error(_mr_t("mktw.err.upload", e=e))
        return {
            "status": "error",
            "message": _mr_t("market.api.upload_failed_detail", detail=str(e)),
            "skill_name": body.skill_name,
            "melted": False,
        }


@router.delete("/skills/{name}", response_model=DeleteResponse)
async def delete_skill(request: Request, name: str):
    skill_market = _get_market(request)
    try:
        # 兼容原有代码的调用方式
        if hasattr(skill_market, "delete_skill") and callable(
            getattr(skill_market, "delete_skill", None)
        ):
            success = (
                await skill_market.delete_skill(name)
                if hasattr(skill_market.delete_skill, "__await__")
                else skill_market.delete_skill(name)
            )
        else:
            success = skill_market.delete_skill(name)
        return {
            "status": "success" if success else "failed",
            "message": (
                _mr_t("market.api.delete_deleted", name=name)
                if success
                else _mr_t("market.api.delete_failed", name=name)
            ),
        }
    except Exception as e:
        logger.error(_mr_t("mktw.err.delete", e=e))
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/health", response_model=MarketHealth)
async def market_health(request: Request):
    """市场健康检查 - 使用 app.state 依赖"""
    try:
        market = getattr(request.app.state, "skill_market", None)
        hunter = getattr(request.app.state, "github_hunter", None)

        total = 0
        if market:
            total = len(await market.list_all_skills())

        hunter_status = "enabled" if hunter else "disabled"
        return {
            "status": "healthy",
            "service": "SkillMarket",
            "github_hunter": hunter_status,
            "total_skills": total,
        }
    except Exception as e:
        logger.error(_mr_t("mktw.err.health", e=e))
        return {
            "status": "healthy",
            "service": "SkillMarket",
            "github_hunter": "disabled",
            "total_skills": 0,
        }


logger.info(boot_t("boot.log.market_routes_loaded"))
# 文件路径: src/adami_kernel/web/market_routes.py (结束)
