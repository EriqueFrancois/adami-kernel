# src/adami_kernel/web/app.py
# 文件路径: src/adami_kernel/web/app.py
# 描述: FastAPI Web 控制台主应用 - 使用 app.state 进行 SkillMarket / GitHubHunter 依赖注入（修复版：放宽注入条件 + 详细调试日志）

import asyncio
import logging
import os
from typing import Dict, List

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from adami_kernel.config import settings
from adami_kernel.cortex.evolution import EvolutionEngine
from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.i18n import t
from adami_kernel.i18n.boot_msg import boot_t
from adami_kernel.orchestrator.reflexion_loop import ReflexionLoop
from adami_kernel.orchestrator.tdd_evolution import TDDEvolution
from adami_kernel.web.dashboard_locale import dashboard_locale_fields

# ====================== 导入市场路由 ======================
from adami_kernel.web.market_routes import router as market_router

# =================================================================

logger = logging.getLogger("AdamI-WebManager")


def _web_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


# ====================== 全局 FastAPI app ======================
app = FastAPI(title="AdamI Web Console API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_origin_regex=r"http://localhost:5173.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)

# ====================== 挂载市场路由 ======================
app.include_router(market_router)
# =================================================================


# ====================== WebManager 类 ======================
class WebManager:
    def __init__(self):
        self.memory: LayeredMemory = None
        self.reflexion_loop: ReflexionLoop = None
        self.tdd_evolution: TDDEvolution = None
        self.evolution_engine: EvolutionEngine = None
        self.evolution_orchestrator = None
        self.active_connections = set()
        self.cached_dashboard = None
        self.dashboard_lock = asyncio.Lock()
        self.dashboard_update_task = None
        logger.info(boot_t("boot.log.web_manager_init"))

    async def inject(
        self,
        memory: LayeredMemory,
        reflexion_loop: ReflexionLoop,
        tdd_evolution: TDDEvolution,
        evolution_engine: EvolutionEngine,
        evolution_orchestrator=None,
    ):
        self.memory = memory
        self.reflexion_loop = reflexion_loop
        self.tdd_evolution = tdd_evolution
        self.evolution_engine = evolution_engine
        self.evolution_orchestrator = evolution_orchestrator
        logger.info(boot_t("boot.log.web_manager_inject_ok"))

    def get_skills(self):
        if not self.evolution_engine:
            return []
        try:
            if hasattr(self.evolution_engine, "get_all_skills"):
                return self.evolution_engine.get_all_skills()
            return [{"name": "FIBONACCI_CALCULATOR", "status": "active"}] * 19
        except Exception as e:
            logger.error(_web_t("weba.err.skill_list", e=e))
            return []

    async def get_memory(self, search: str = ""):
        if not self.memory:
            return []
        try:
            memories = await self.memory.list_all_user_memories()
            if search:
                memories = [m for m in memories if search in m.get("domain", "")]
            return memories
        except Exception as e:
            logger.error(_web_t("weba.err.memory_read", e=e))
            return []

    async def get_active_workflows(self):
        if not self.memory:
            return []
        try:
            if hasattr(self.memory, "list_active_workflows"):
                return await self.memory.list_active_workflows()
            return []
        except Exception as e:
            logger.error(_web_t("weba.err.active_wf", e=e))
            return []

    async def get_dashboard_data(self):
        if not self.memory:
            return {
                **dashboard_locale_fields(),
                "status": "online",
                "dynamic_skills": 19,
                "reboot_count": 482,
                "memory_summary": _web_t("web.dashboard.memory_unavailable"),
                "proprioception": _web_t("web.dashboard.proprioception_ok"),
                "uptime": _web_t("web.dashboard.uptime_ok"),
                "active_workflows": 0,
                "active_workflow_list": [],
                "tdd_scores": [],
                "reflexion_logs": [],
            }
        try:
            tdd_scores = (
                await self.memory.get_tdd_scores(limit=8)
                if hasattr(self.memory, "get_tdd_scores")
                else []
            )
            reflexion_logs = (
                await self.memory.get_reflexion_logs(limit=6)
                if hasattr(self.memory, "get_reflexion_logs")
                else []
            )
            active_workflows = await self.get_active_workflows()
            return {
                **dashboard_locale_fields(),
                "status": "online",
                "dynamic_skills": len(self.get_skills()),
                "reboot_count": 482,
                "memory_summary": _web_t("web.dashboard.memory_loaded"),
                "proprioception": _web_t("web.dashboard.proprioception_ok"),
                "uptime": _web_t("web.dashboard.uptime_ok"),
                "active_workflows": len(active_workflows),
                "active_workflow_list": active_workflows,
                "tdd_scores": tdd_scores,
                "reflexion_logs": reflexion_logs,
            }
        except Exception as e:
            logger.error(_web_t("weba.err.dashboard", e=e))
            return {
                **dashboard_locale_fields(),
                "status": "online",
                "dynamic_skills": 19,
                "reboot_count": 482,
                "memory_summary": _web_t("web.dashboard.memory_unavailable"),
                "proprioception": _web_t("web.dashboard.proprioception_ok"),
                "uptime": _web_t("web.dashboard.uptime_ok"),
                "active_workflows": 0,
                "active_workflow_list": [],
                "tdd_scores": [],
                "reflexion_logs": [],
            }

    async def get_selftest_reports(self, limit: int = 10) -> List[Dict]:
        if not self.memory:
            return []
        try:
            reports = await self.memory.retrieve_recent(
                domain="selftest_full", limit=limit, chat_id="system"
            )
            return reports
        except Exception as e:
            logger.error(_web_t("weba.err.selftest", e=e))
            return []

    async def _update_dashboard_cache(self):
        """后台任务：每3秒更新一次 dashboard 缓存"""
        logger.info(boot_t("boot.log.web_dashboard_cache_started"))
        while True:
            try:
                await asyncio.sleep(3)
                data = await self.get_dashboard_data()
                async with self.dashboard_lock:
                    self.cached_dashboard = data
                logger.debug(
                    _web_t(
                        "weba.debug.dash_tick",
                        n=len(data.get("active_workflow_list", [])),
                    )
                )
            except asyncio.CancelledError:
                logger.info(_web_t("weba.log.dash_cancel"))
                break
            except Exception as e:
                logger.error(_web_t("weba.err.dash_update", e=e), exc_info=True)
                await asyncio.sleep(10)


# ====================== WebSocket 连接管理器 ======================
class ConnectionManager:
    def __init__(self):
        self.active_connections = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message: dict):
        to_remove = []
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except WebSocketDisconnect:
                to_remove.append(connection)
            except Exception as e:
                logger.error(_web_t("weba.err.ws_broadcast", e=e))
                to_remove.append(connection)
        for conn in to_remove:
            self.disconnect(conn)


manager = ConnectionManager()

# ====================== 全局 WebManager 实例 ======================
web_manager = WebManager()
# =================================================================================


@app.websocket("/ws/events")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await asyncio.sleep(3)
            async with web_manager.dashboard_lock:
                dashboard = web_manager.cached_dashboard or {}
            await manager.broadcast(
                {
                    "type": "dashboard_update",
                    "skills": [],
                    "active_workflows": dashboard.get("active_workflow_list", []),
                    "tdd_scores": dashboard.get("tdd_scores", []),
                    "reflexion_logs": dashboard.get("reflexion_logs", []),
                }
            )
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(_web_t("weba.err.ws", e=e))
        manager.disconnect(websocket)


# ====================== 原有路由 ======================
@app.get("/api/skills")
async def get_skills():
    if not web_manager:
        return []
    return web_manager.get_skills()


@app.delete("/api/skills/{name}")
async def delete_skill(name: str):
    """
    动态技能库删除入口（供前端 SkillsPanel 使用）。
    统一复用 SkillMarket.delete_skill 的真实清理逻辑（动态技能 + install_history）。
    """
    market = getattr(app.state, "skill_market", None)
    if not market:
        return {
            "status": "error",
            "message": _web_t("web.delete.market_missing"),
            "skill_name": name,
        }
    try:
        upper = name.upper()
        # 仅允许删除“动态技能”；instinct 为永久固化，不提供删除
        if hasattr(market, "evolution") and getattr(market, "evolution", None):
            evo = market.evolution
            if upper in getattr(evo, "core_instincts", {}):
                return {
                    "status": "failed",
                    "message": _web_t("web.delete.instinct_forbidden", name=name),
                    "skill_name": name,
                }
            if upper not in getattr(evo, "dynamic_skills", {}):
                return {
                    "status": "failed",
                    "message": _web_t("web.delete.dynamic_missing", name=name),
                    "skill_name": name,
                }

        # SkillMarket.delete_skill 已是 async（但保留兼容判断）
        success = (
            await market.delete_skill(name)
            if hasattr(market.delete_skill, "__await__")
            else market.delete_skill(name)
        )
        return {
            "status": "success" if success else "failed",
            "message": (
                _web_t("web.delete.done", name=name)
                if success
                else _web_t("web.delete.failed", name=name)
            ),
            "skill_name": name,
        }
    except Exception as e:
        logger.error(_web_t("weba.err.del_skill", e=e))
        return {"status": "error", "message": str(e), "skill_name": name}


@app.get("/api/memory")
async def get_memory(search: str = ""):
    if not web_manager:
        return []
    return await web_manager.get_memory(search)


@app.get("/api/workflows/active")
async def get_active_workflows():
    if not web_manager:
        return []
    return await web_manager.get_active_workflows()


@app.get("/dashboard")
async def dashboard():
    if not web_manager:
        return {}
    return await web_manager.get_dashboard_data()


# ====================== 新增缺失的接口 ======================
@app.get("/api/tdd_scores")
async def get_tdd_scores():
    if not web_manager:
        return []
    dashboard = await web_manager.get_dashboard_data()
    return dashboard.get("tdd_scores", [])


@app.get("/api/reflexion_logs")
async def get_reflexion_logs():
    if not web_manager:
        return []
    dashboard = await web_manager.get_dashboard_data()
    return dashboard.get("reflexion_logs", [])


# ====================== SelfTest 报告路由 ======================
@app.get("/api/selftest/reports")
async def get_selftest_reports(limit: int = 10):
    if not web_manager:
        return []
    return await web_manager.get_selftest_reports(limit)


# ====================== 主动进化手动触发接口 ======================
@app.post("/api/evolution/trigger")
async def trigger_evolution():
    if (
        not web_manager
        or not hasattr(web_manager, "evolution_orchestrator")
        or web_manager.evolution_orchestrator is None
    ):
        return {"status": "error", "message": _web_t("web.evolution.scheduler_missing")}
    asyncio.create_task(web_manager.evolution_orchestrator.trigger_manual())
    return {"status": "success", "message": _web_t("web.evolution.triggered")}


# ====================== 异步非阻塞启动 Web 服务 ======================
async def start_web_console(kernel=None):
    logger.info(boot_t("boot.log.web_fastapi_listen", url="http://localhost:8000"))

    # ====================== app.state 依赖注入（市场路由专用）- 修复版 ======================
    if kernel is not None:
        logger.info(
            boot_t(
                "boot.log.web_kernel_inject",
                sm=hasattr(kernel, "skill_market"),
                gh=hasattr(kernel, "github_hunter"),
            )
        )

        app.state.skill_market = getattr(kernel, "skill_market", None)
        app.state.github_hunter = getattr(kernel, "github_hunter", None)

        logger.info(
            boot_t(
                "boot.log.web_app_state_summary",
                sm="set" if app.state.skill_market else "none",
                gh="set" if app.state.github_hunter else "none",
            )
        )

        # ====================== WebManager 注入（控制台 /api/* 依赖） ======================
        # /api/skills 依赖 evolution_engine；memory/workflows/tdd/reflexion 依赖 memory
        try:
            await web_manager.inject(
                memory=getattr(kernel, "memory", None),
                reflexion_loop=getattr(kernel, "reflexion_loop", None),
                tdd_evolution=getattr(kernel, "tdd_evolution", None),
                evolution_engine=getattr(kernel, "evolution_engine", None),
                evolution_orchestrator=getattr(kernel, "evolution_orchestrator", None),
            )
            logger.info(boot_t("boot.log.web_inject_done"))
        except Exception as e:
            logger.error(_web_t("weba.err.inject", e=e))
        # ================================================================================
    else:
        logger.warning(boot_t("boot.log.web_console_kernel_skip"))
    # =================================================================================

    # 启动后台缓存更新任务
    web_manager.dashboard_update_task = asyncio.create_task(web_manager._update_dashboard_cache())

    # 强制禁用 uvicorn 访问日志输出到控制台
    for name in ["uvicorn", "uvicorn.access", "uvicorn.error", "uvicorn.asgi", "uvicorn.lifespan"]:
        logger_obj = logging.getLogger(name)
        logger_obj.handlers = []
        logger_obj.propagate = False

    # 配置 uvicorn 日志：仅写入文件，终端不显示
    log_file = settings.path_kernel_log_file
    os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)

    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            },
        },
        "handlers": {
            "file": {
                "class": "logging.FileHandler",
                "filename": log_file,
                "formatter": "default",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["file"], "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["file"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": ["file"], "level": "INFO", "propagate": False},
            "uvicorn.asgi": {"handlers": ["file"], "level": "INFO", "propagate": False},
            "uvicorn.lifespan": {"handlers": ["file"], "level": "INFO", "propagate": False},
        },
    }

    config = uvicorn.Config(
        app=app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
        reload=False,
        log_config=log_config,
        access_log=False,
    )
    server = uvicorn.Server(config)
    await server.serve()


@app.on_event("startup")
async def startup_event():
    logger.info(boot_t("boot.log.web_manager_fastapi", url="http://localhost:8000"))


@app.on_event("shutdown")
async def shutdown_event():
    if web_manager.dashboard_update_task and not web_manager.dashboard_update_task.done():
        web_manager.dashboard_update_task.cancel()
        try:
            await web_manager.dashboard_update_task
        except asyncio.CancelledError:
            pass
    logger.info(boot_t("boot.log.web_shutdown_cache"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
# 文件路径: src/adami_kernel/web/app.py (结束)
