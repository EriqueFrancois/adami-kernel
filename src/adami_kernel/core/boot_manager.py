# src/adami_kernel/core/boot_manager.py
# 文件路径: src/adami_kernel/core/boot_manager.py
# 版本：v2.3（Web Console 启动统一收敛到 BootManager + app.state 注入优化）
# 修改时间：2026-04-08
# 修复目的：将启动逻辑集中到 BootManager（用户审计意见），彻底解决端口冲突 + 注入时序问题

import asyncio
import logging
import platform
import subprocess
from datetime import datetime
from typing import Any, Dict

import httpx

from adami_kernel.config import settings
from adami_kernel.hippocampus.db_helper import DatabaseHelper
from adami_kernel.i18n.boot_msg import boot_t
from adami_kernel.nexus.shell import InteractiveShell
from adami_kernel.nexus.skill_loader import SkillLoader
from adami_kernel.orchestrator.agent_models import AgentRole
from adami_kernel.skill_manager.skill_metadata import SkillMetadata, SkillVersion
from adami_kernel.skill_manager.vector_store import VectorStore

# ====================== 可选代理类（与 component_initializer.py 保持一致） ======================
Researcher = None
try:
    from adami_kernel.orchestrator.agents.researcher import Researcher
except ImportError:
    pass

Engineer = None
try:
    from adami_kernel.orchestrator.agents.engineer import Engineer
except ImportError:
    pass

Critic = None
try:
    from adami_kernel.orchestrator.agents.critic import Critic
except ImportError:
    pass

Human = None
try:
    from adami_kernel.orchestrator.agents.human import Human
except ImportError:
    pass

ExecutorAgent = None
try:
    from adami_kernel.orchestrator.agents.executor import ExecutorAgent
except ImportError:
    pass
# =================================================================================

# ====================== 【本次修复】hitl_handler 全局导入 ======================
from adami_kernel.orchestrator.hitl_handler import hitl_handler

# =================================================================================

# ====================== Web Console 启动函数（可选） ======================
start_web_console = None
try:
    from adami_kernel.web.app import start_web_console  # type: ignore
except Exception:  # pragma: no cover
    start_web_console = None  # type: ignore[assignment]
# ======================================================================

logger = logging.getLogger("AdamI-BootManager")


class BootManager:
    """
    工业级启动管理器（单一职责）
    【v2.3 核心变更】：Web Console 启动 + app.state 注入统一收敛到 BootManager（用户审计意见）
    【v2.2 遗留功能】：hitl_handler 前置初始化 + registry.initialize_all() 去重
    """

    def __init__(self, components: Dict[str, Any]):
        self.components = components
        logger.info("Initializing BootManager")

    async def _ensure_skill_metadata(self):
        """为所有已加载的技能创建或更新元数据（若无）。"""
        if not self.components.get("skill_manager"):
            return
        all_skills = self.components["evolution_engine"].get_all_skills()
        filled = 0
        for skill in all_skills:
            skill_name = skill["name"]
            existing = await self.components["skill_manager"].get_skill_metadata(skill_name)
            if existing is None:
                metadata = SkillMetadata(
                    skill_name=skill_name.upper(),
                    current_version="v1.0",
                    score=100.0,
                    versions={
                        "v1.0": SkillVersion(
                            version="v1.0",
                            code="",
                            score=100.0,
                            reason=boot_t("boot.skill_metadata_initial_reason"),
                        )
                    },
                    metrics={
                        "total_calls": 0,
                        "success_calls": 0,
                        "consecutive_failures": 0,
                        "last_used": None,
                    },
                    status="active",
                )
                payload = metadata.model_dump()
                if "created_at" in payload and isinstance(payload["created_at"], datetime):
                    payload["created_at"] = payload["created_at"].isoformat()
                if "updated_at" in payload and isinstance(payload["updated_at"], datetime):
                    payload["updated_at"] = payload["updated_at"].isoformat()
                for ver in payload.get("versions", {}).values():
                    if "created_at" in ver and isinstance(ver["created_at"], datetime):
                        ver["created_at"] = ver["created_at"].isoformat()
                await self.components["memory"].store_experience(
                    trace_id=f"skill_metadata_init_{skill_name}",
                    domain="skill_metadata",
                    payload=payload,
                    chat_id="system",
                )
                filled += 1
        if filled:
            logger.info("[BootManager][SLM] filled default metadata for %d skill(s)", filled)

    async def _auto_start_ollama(self) -> None:
        """工业级 Ollama 自动启动（多平台适配 + 幂等 + 健康等待）"""
        ollama_host = "http://127.0.0.1:11434"
        is_linux = platform.system().lower() == "linux"

        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{ollama_host}/api/version")
                if resp.status_code == 200:
                    logger.info(boot_t("boot.ollama_running_skip"))
                    return
        except Exception:
            pass

        logger.info(boot_t("boot.ollama_starting"))
        try:
            if is_linux:
                subprocess.run(["systemctl", "start", "ollama"], check=True, capture_output=True)
                logger.info(boot_t("boot.ollama_systemctl_ok"))
            else:
                subprocess.Popen(
                    ["ollama", "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                logger.info(boot_t("boot.ollama_popen_ok"))

            for i in range(15):
                await asyncio.sleep(1.0)
                try:
                    async with httpx.AsyncClient(timeout=2.0) as client:
                        resp = await client.get(f"{ollama_host}/api/version")
                        if resp.status_code == 200:
                            logger.info(boot_t("boot.ollama_ready_wait_secs", secs=i + 1))
                            return
                except Exception:
                    pass
            logger.warning(boot_t("boot.ollama_still_not_ready"))
        except Exception as e:
            logger.error(boot_t("boot.ollama_start_failed", detail=str(e)))

    async def boot(self) -> None:
        """完整启动流程（原 kernel.py boot() 全部逻辑）"""
        logger.info(boot_t("boot.boot_sequence_start"))

        # ====================== 【阶段1 关键新增】SecondBrain 初始化 ======================
        if self.components.get("second_brain"):
            await self.components["second_brain"].initialize()
            logger.info("[BootManager] SecondBrain ready")
            # 【小条5 / 步骤10】startup hook：第二大脑健康摘要（只读）
            try:
                logger.info(
                    boot_t(
                        "boot.secondbrain_health_log",
                        summary=self.components["second_brain"].brain_health_summary(),
                    ),
                )
            except Exception as e:
                logger.warning(boot_t("boot.secondbrain_health_fail", detail=str(e)))
        # =================================================================================

        # ====================== 【本次修复】hitl_handler 初始化（nerve_registry / registry.initialize_all() 之前） ======================
        if hitl_handler is not None and hasattr(hitl_handler, "initialize"):
            await hitl_handler.initialize()
            logger.info(boot_t("boot.hitl_init_ok"))
        # =================================================================================

        # ====================== Ollama 自动启动 ======================
        if getattr(settings, "OLLAMA_AUTO_START", True):
            await self._auto_start_ollama()
        # ============================================================

        # 1. 数据库 WAL 预处理
        await DatabaseHelper.close_all()
        await DatabaseHelper.ensure_wal(settings.path_l2_memory_db)
        await DatabaseHelper.ensure_wal(settings.path_dlq_db)
        await DatabaseHelper.ensure_wal(settings.path_subconscious_db)
        logger.info(boot_t("boot.db_wal_ok"))

        # 2. 强化学习循环初始化
        if hasattr(self.components["rl_loop"], "initialize"):
            await self.components["rl_loop"].initialize()
            logger.info(boot_t("boot.rl_loop_ok"))

        # 3. 核心服务初始化
        await self.components["bus"].initialize()
        from adami_kernel.guardian.rbac_initializer import RBACInitializer

        RBACInitializer.initialize(self.components["rbac"])
        self.components["bus"].set_rbac(self.components["rbac"])

        await self.components["memory"].initialize()
        await self.components["subconscious"].initialize()
        await self.components["toolbox"].initialize_environment()

        if self.components.get("dlq"):
            await self.components["dlq"].init_db()
            self.components["bus"].dlq_db = self.components["dlq"]

        # 3.8 SkillVersionManager：先于技能文件加载初始化缓存，保证 is_instinct / 路由一致
        if self.components.get("skill_version_manager"):
            try:
                await self.components["skill_version_manager"].initialize()
                logger.info(boot_t("boot.skill_version_ok"))
            except Exception as e:
                logger.error(boot_t("boot.skill_version_fail", detail=str(e)))
        else:
            logger.warning(boot_t("boot.skill_version_skip"))

        # 4. 进化引擎与技能加载
        await self.components["evolution_engine"].load_genetic_skills()
        await SkillLoader.load(self.components)
        if self.components.get("skill_manager"):
            self.components["skill_manager"].refresh_instinct_cache_from_disk()

        # 5. SelfTestEngine 初始化
        if self.components.get("self_test_engine"):
            try:
                await self.components["self_test_engine"].initialize()
                logger.info(boot_t("boot.selftest_engine_ok"))
            except Exception as e:
                logger.error(boot_t("boot.selftest_engine_fail", detail=str(e)))
                self.components["self_test_engine"] = None

        # 6. VectorStore 初始化（三重强制注入，最终根治警告）
        try:
            if (
                hasattr(self.components["memory"], "chroma_client")
                and self.components["memory"].chroma_client
            ):
                self.components["vector_store"] = VectorStore(
                    memory=self.components["memory"],
                    chroma_client=self.components["memory"].chroma_client,
                )
                logger.info(boot_t("boot.vector_store_ok"))
                await asyncio.sleep(0.1)  # 微等待，确保内存就绪
                await self.components["vector_store"].initialize()
                await self.components["vector_store"].rebuild_index()

                # 三重强制注入
                if self.components.get("skill_router") and hasattr(
                    self.components["skill_router"], "set_vector_store"
                ):
                    self.components["skill_router"].set_vector_store(
                        self.components["vector_store"]
                    )
                    logger.info(boot_t("boot.vector_router_inject"))

                if self.components.get("skill_manager") and hasattr(
                    self.components["skill_manager"], "set_vector_store"
                ):
                    self.components["skill_manager"].set_vector_store(
                        self.components["vector_store"]
                    )
                    logger.info(boot_t("boot.vector_manager_inject"))

                # SkillCleaner 在 ComponentInitializer 中已实例化，需同步替换其持有的旧 vector_store 引用
                if (
                    self.components.get("skill_cleaner")
                    and getattr(self.components["skill_cleaner"], "vector_store", None)
                    is not self.components["vector_store"]
                ):
                    try:
                        self.components["skill_cleaner"].vector_store = self.components[
                            "vector_store"
                        ]
                        logger.info(boot_t("boot.vector_cleaner_inject"))
                    except Exception:
                        pass

                # 第三重保险：Registry 注册
                if self.components.get("registry"):
                    self.components["registry"].register(
                        "vector_store", self.components["vector_store"]
                    )
            else:
                logger.warning(boot_t("boot.chromadb_fallback"))
        except Exception as e:
            logger.error(boot_t("boot.vector_store_fail", detail=str(e)))
            self.components["vector_store"] = None

        # 6.5 MCP 工具加载：不在 Boot 阶段阻塞；由 LifecycleManager 后台任务异步初始化 + 热更新

        # 7. 注册与元数据补全
        self.components["registry"].register("skill_router", self.components.get("skill_router"))
        self.components["registry"].register("vector_store", self.components.get("vector_store"))

        if self.components.get("skill_manager") and self.components.get("vector_store"):
            if hasattr(self.components["skill_manager"], "set_vector_store"):
                self.components["skill_manager"].set_vector_store(self.components["vector_store"])
                logger.info(boot_t("boot.vector_manager_inject2"))

        if self.components.get("skill_manager"):
            await self._ensure_skill_metadata()

        # 8. 定时任务注册
        if self.components.get("skill_cleaner"):
            self.components["ans"].register_rhythm(
                "skill_cleaner",
                settings.ADAMI_BOOT_SKILL_CLEANER_INTERVAL_SEC,
                self.components["skill_cleaner"].clean,
            )
            logger.info(
                boot_t(
                    "boot.skill_cleaner_registered",
                    sec=settings.ADAMI_BOOT_SKILL_CLEANER_INTERVAL_SEC,
                ),
            )

        if self.components.get("skill_version_manager") and self.components.get("skill_optimizer"):
            self.components["ans"].register_skill_optimizer(
                skill_version_manager=self.components["skill_version_manager"],
                skill_optimizer=self.components["skill_optimizer"],
                skill_factory=getattr(self.components["evolution_engine"], "code_generator", None),
                interval_hours=settings.ADAMI_BOOT_SKILL_OPTIMIZER_INTERVAL_HOURS,
            )
            logger.info(
                boot_t(
                    "boot.skill_optimizer_registered",
                    hours=settings.ADAMI_BOOT_SKILL_OPTIMIZER_INTERVAL_HOURS,
                ),
            )

        # 9. 插件注册器统一初始化（所有注册的模块在此处已完成 initialize()，包括 MultiAgentOrchestrator 等）
        await self.components["registry"].initialize_all()

        try:
            from adami_kernel.orchestrator.diagnostics import SystemDiagnostics
            from adami_kernel.orchestrator.diagnostics_view import ComponentsKernelView

            SystemDiagnostics.perform_startup_check(ComponentsKernelView(self.components))
        except Exception as e:
            logger.warning(boot_t("boot.log.diag_failed", detail=str(e)))

        # 10. 神经节律与 GraphMemory
        asyncio.create_task(self.components["circadian_nerve"].start())
        if self.components.get("report_scheduler"):
            asyncio.create_task(self.components["report_scheduler"].start())
        if (
            self.components.get("meta_cortex")
            and self.components["meta_cortex"].graph_memory.enabled
        ):
            await self.components["meta_cortex"].graph_memory.initialize()

        # 11. 多代理与 Workflow 初始化
        self.components["multi_agent_orchestrator"].set_evolution_engine(
            self.components["evolution_engine"]
        )
        self.components["multi_agent_orchestrator"].set_router(self.components["router"])
        if self.components.get("skill_router"):
            self.components["multi_agent_orchestrator"].set_skill_router(
                self.components["skill_router"]
            )

        # ====================== 【步骤4】WorkflowEngine 执行 SkillComposer DAG 需 evolution_engine ======================
        if self.components.get("workflow_engine") and self.components.get("evolution_engine"):
            self.components["workflow_engine"].set_evolution_engine(
                self.components["evolution_engine"]
            )
        # =================================================================================

        # ====================== 【核心修复】移除重复调用 ======================
        # 移除已下重复的 initialize()，因为它们在第9步的 registry.initialize_all() 已被执行
        # await self.components["workflow_engine"].initialize()
        # await self.components["multi_agent_orchestrator"].initialize()
        # if hasattr(self.components["reflexion_loop"], "initialize"):
        #     await self.components["reflexion_loop"].initialize()
        # await self.components["planner"].initialize()
        # ====================================================================

        # 12. 运行状态与 WebConsole（统一由 BootManager 负责）
        self.components["_running"] = True
        total_modules = len(self.components["registry"].plugins) + 5
        from rich.console import Console

        console = Console()
        console.print(boot_t("boot.selftest_pass_simple", n=total_modules))

        # ====================== 【本次核心优化】Web Console + app.state 注入 ======================
        # 从 components 安全提取 kernel 对象（兼容 kernel.py 传递方式）
        kernel = self.components.get("kernel") or type("Kernel", (), self.components)()
        if start_web_console is not None:
            logger.info(boot_t("boot.web_console_start"))
            self.components["web_console_task"] = asyncio.create_task(
                start_web_console(kernel=kernel)
            )
            logger.info(boot_t("boot.web_console_started"))
        else:
            logger.info(boot_t("boot.web_console_skip"))
        # =================================================================================

        # 【新增】CLI InteractiveShell 配置（确保事件携带 platform="cli" 和 chat_id="cli"）
        self.shell = InteractiveShell(self)
        # 确保 CLI 事件携带正确参数（chat_id="cli" + platform="cli"）
        self.components["cli_chat_id"] = "cli"
        self.components["cli_platform"] = "cli"
        logger.info(boot_t("boot.shell_cli_started"))
        # =================================================================================

        # 13. SelfModel 灵魂苏醒（跨文件防重复）
        if self.components.get("self_model"):
            if not getattr(self.components["self_model"], "_initialized", False):
                self.components["self_model"]._initialized = True
                logger.info(boot_t("boot.selfmodel_log_init"))
            else:
                logger.debug(boot_t("boot.selfmodel_log_skip"))

            rules = await self.components["memory"].retrieve_recent("semantic_rules", 5)
            rules_str = (
                " ".join([r.get("insight", "") for r in rules])
                if rules
                else boot_t("boot.rules_empty")
            )
            awakening_thought = await self.components["self_model"].reflect_and_awaken(
                self.components["router"],
                self.components.get("base_persona", ""),
                self.components["evolution_engine"].get_persona_additions()
                or boot_t("boot.persona_additions_none"),
                rules_str,
            )
            await self.components["memory"].store_experience(
                f"reboot_{self.components['self_model'].reboot_count}",
                "semantic_rules",
                {
                    "insight": boot_t(
                        "boot.awakening_insight_record",
                        count=self.components["self_model"].reboot_count,
                        thought=awakening_thought,
                    )
                },
            )
            console.print(
                boot_t(
                    "boot.awakening_banner",
                    reboot_count=self.components["self_model"].reboot_count,
                )
            )

        # 14. Observability & HITL（原有逻辑保留，作为双保险）
        if await self.components["observability"].is_enabled():
            logger.info(boot_t("boot.observability_on"))
        if hasattr(self.components["hitl_handler"], "initialize") and asyncio.iscoroutinefunction(
            self.components["hitl_handler"].initialize
        ):
            await self.components["hitl_handler"].initialize()
            logger.info(boot_t("boot.hitl_listener_started"))

        # 15. 多代理注册
        if self.components.get("multi_agent_orchestrator"):
            for role, agent_class in [
                (AgentRole.RESEARCHER, Researcher),
                (AgentRole.ENGINEER, Engineer),
                (AgentRole.CRITIC, Critic),
                (AgentRole.HUMAN, Human),
            ]:
                if agent_class is not None:
                    if role == AgentRole.CRITIC:
                        agent = agent_class(
                            self.components["memory"],
                            self.components["episodic_memory"],
                            self.components["router"],
                        )
                    elif role == AgentRole.ENGINEER and self.components.get("skill_manager"):
                        agent = agent_class(
                            self.components["toolbox"],
                            self.components["memory"],
                            self.components["evolution_engine"],
                            self.components["skill_manager"],
                        )
                    else:
                        agent = (
                            agent_class(self.components["toolbox"], self.components["memory"])
                            if role != AgentRole.HUMAN
                            else agent_class(
                                self.components["memory"],
                                self.components.get("telegram_nerve"),
                                self.components.get("discord_nerve"),
                            )
                        )
                    self.components["multi_agent_orchestrator"].register_agent(role, agent)
                    logger.info(boot_t("boot.agent_registered", role=role.value))
                else:
                    logger.warning(boot_t("boot.agent_register_import_fail", role=role.value))

            executor_agent = ExecutorAgent(
                self.components["evolution_engine"],
                self.components["memory"],
                skill_router=self.components.get("skill_router"),
                skill_version_manager=self.components.get("skill_version_manager"),
            )
            self.components["multi_agent_orchestrator"].register_agent(
                AgentRole.EXECUTOR, executor_agent
            )
            logger.info(boot_t("boot.executor_registered"))

        # 16. 最后注入与主动进化
        if hasattr(self.components["reflexion_loop"], "workflow_engine"):
            self.components["reflexion_loop"].workflow_engine = self.components["workflow_engine"]
        if hasattr(self.components["tdd_evolution"], "router"):
            self.components["tdd_evolution"].router = self.components["router"]

        if self.components.get("evolution_orchestrator") and settings.ADAMI_AUTO_EVOLUTION_ENABLED:
            asyncio.create_task(self.components["evolution_orchestrator"].start())
            logger.info(boot_t("boot.auto_evo_on"))
        else:
            logger.info(boot_t("boot.auto_evo_off"))

        logger.info(boot_t("boot.boot_complete"))


# --- END OF FILE src/adami_kernel/core/boot_manager.py ---
# 文件路径：src/adami_kernel/core/boot_manager.py
