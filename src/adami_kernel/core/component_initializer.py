# 文件路径：src/adami_kernel/core/component_initializer.py
# 版本：v2.3（去除 market_routes 全局注入 + SkillOptimizer SelfTestRunner 真实注入版）
# 修改时间：2026-04-08
# 修复目的：彻底切断 core → web 的全局注入耦合，改为 app.state 依赖注入模式

import asyncio
import logging
from typing import Any, Dict, Optional

from adami_kernel.cortex.evolution import EvolutionEngine
from adami_kernel.cortex.prompt import PromptBuilder
from adami_kernel.cortex.reinforcement import rl_loop
from adami_kernel.cortex.router import hybrid_router
from adami_kernel.cortex.tools_manager import ToolboxManager
from adami_kernel.guardian.immunity import ImmunitySystem
from adami_kernel.guardian.limiter import TokenBucketLimiter
from adami_kernel.guardian.rbac import RBACMatrix
from adami_kernel.guardian.tls import LocalSecretVault
from adami_kernel.hippocampus.consolidation import SemanticConsolidator
from adami_kernel.hippocampus.episodic_memory import EpisodicMemory
from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.hippocampus.subconscious import SubconsciousRAG
from adami_kernel.i18n.boot_msg import boot_t
from adami_kernel.nexus.bus import EventBus
from adami_kernel.nexus.health_server import HealthServer
from adami_kernel.nexus.nerve_registry import NerveRegistry
from adami_kernel.nexus.pulse import AutonomicNervousSystem
from adami_kernel.orchestrator.fitness import FitnessEvaluator
from adami_kernel.orchestrator.planner import TaskPlanner
from adami_kernel.policy.loader import PolicyLoader, set_policy_loader

start_web_console = None
try:  # optional web console (FastAPI)
    from adami_kernel.web.app import start_web_console  # type: ignore
except Exception:  # pragma: no cover
    start_web_console = None  # type: ignore[assignment]

# ====================== 【2.0 阶段】各引擎 ======================
import adami_kernel.orchestrator.hitl_handler as hitl_handler_module

# ====================== MCP（stdio + Docker 隔离） ======================
from adami_kernel.mcp.manager import McpManager

# ====================== 可选模块（try/except） ======================
from adami_kernel.orchestrator.hitl_handler import HitlHandler
from adami_kernel.orchestrator.multi_agent_orchestrator import MultiAgentOrchestrator
from adami_kernel.orchestrator.multi_tenant_guard import multi_tenant_guard
from adami_kernel.orchestrator.reflexion_loop import ReflexionLoop
from adami_kernel.orchestrator.skill_composer import SkillComposer
from adami_kernel.orchestrator.tdd_evolution import TDDEvolution
from adami_kernel.orchestrator.workflow_engine import WorkflowEngine
from adami_kernel.self_test.self_test_engine import SelfTestEngine

# ====================== 【SkillManager 全系列】 ======================
from adami_kernel.skill_manager import SkillManager
from adami_kernel.skill_manager.skill_cleaner import SkillCleaner
from adami_kernel.skill_manager.skill_optimizer import SkillOptimizer
from adami_kernel.skill_manager.skill_router import SkillRouter
from adami_kernel.skill_manager.skill_version_manager import SkillVersionManager
from adami_kernel.skill_manager.vector_store import VectorStore
from adami_kernel.web.observability import observability

# 可选神经/沙盒等
try:
    from adami_kernel.cortex.sub_agent import SubAgentManager
except ImportError:
    SubAgentManager = None
try:
    from adami_kernel.nexus.sensory import SensoryNervousSystem
except ImportError:
    SensoryNervousSystem = None
try:
    from adami_kernel.nexus.proprioception import ProprioceptiveSystem
except ImportError:
    ProprioceptiveSystem = None
try:
    from adami_kernel.nexus.dlq import DeadLetterQueue
except ImportError:
    DeadLetterQueue = None
try:
    from adami_kernel.cortex.claw_hub import ClawHub
except ImportError:
    ClawHub = None
try:
    from adami_kernel.cortex.meta_cortex import MetaCortex
except ImportError:
    MetaCortex = None
try:
    from adami_kernel.cortex.self_model import SelfModel
except ImportError:
    SelfModel = None
try:
    from adami_kernel.cortex.dream_sandbox import DreamSandbox
except ImportError:
    DreamSandbox = None
try:
    from adami_kernel.cortex.intent_router import SemanticIntentRouter
except ImportError:
    SemanticIntentRouter = None

# 【阶段1 新增】第二大脑管理器（SecondBrainManager）
from adami_kernel.hippocampus.second_brain import SecondBrainManager
from adami_kernel.market.github_hunter import GitHubHunter
from adami_kernel.market.skill_market import SkillMarket
from adami_kernel.peripheral.circadian_nerve import CircadianNerve
from adami_kernel.peripheral.report_studio.report_scheduler import ReportScheduler

logger = logging.getLogger("AdamI-ComponentInitializer")


class PluginRegistry:
    def __init__(self):
        self.plugins: Dict[str, Any] = {}

    def register(self, name: str, instance: Any):
        self.plugins[name] = instance
        logger.debug("[Registry] registered module %s", name)

    def get(self, name: str) -> Optional[Any]:
        return self.plugins.get(name)

    async def initialize_all(self):
        for name, plugin in self.plugins.items():
            if hasattr(plugin, "initialize") and asyncio.iscoroutinefunction(plugin.initialize):
                await plugin.initialize()
                logger.debug("[Registry] module %s initialized", name)
            elif hasattr(plugin, "initialize"):
                plugin.initialize()
                logger.debug("[Registry] module %s initialized (sync)", name)


class TaskFailedException(Exception):
    pass


class ComponentInitializer:
    """
    工业级组件工厂（单一职责）
    负责 AdamiKernel 所有组件的实例化、依赖注入、条件创建
    【v2.3 核心变更】：彻底移除 market_routes 全局注入，全部改为 app.state 模式
    【v2.2 遗留功能】：SkillOptimizer 显式注入 SelfTestRunner 真实执行器 + health_server 始终存在
    """

    def __init__(self):
        logger.info("Initializing ComponentInitializer")

    def initialize_components(self, kernel=None) -> Dict[str, Any]:
        """返回所有组件字典，供 kernel.py 使用"""
        components: Dict[str, Any] = {}
        self.kernel = kernel

        # ====================== 基础组件 ======================
        components["bus"] = EventBus()
        components["limiter"] = TokenBucketLimiter()
        components["rbac"] = RBACMatrix()
        components["memory"] = LayeredMemory()
        components["toolbox"] = ToolboxManager()
        components["ans"] = AutonomicNervousSystem(components["bus"].publish)
        components["subconscious"] = SubconsciousRAG()
        components["tls_vault"] = LocalSecretVault()
        components["episodic_memory"] = EpisodicMemory()
        components["dream_sandbox"] = DreamSandbox() if DreamSandbox else None
        components["immunity"] = ImmunitySystem()

        # ====================== 【阶段1 新增】第二大脑管理器 ======================
        components["second_brain"] = SecondBrainManager()
        logger.debug("[ComponentInitializer] SecondBrainManager ready")

        # ====================== Router 提前注入 ======================
        components["router"] = hybrid_router
        if hasattr(components["toolbox"], "set_router"):
            components["toolbox"].set_router(components["router"])
            logger.debug("[Toolbox] router set on ToolboxManager")

        components["evolution_engine"] = EvolutionEngine(
            toolbox=components["toolbox"],
            memory=components["memory"],
            dream_sandbox=components["dream_sandbox"],
        )

        components["mcp_manager"] = McpManager(evolution_engine=components["evolution_engine"])

        components["consolidator"] = SemanticConsolidator(
            components["memory"], components["router"]
        )
        components["rl_loop"] = rl_loop

        if hasattr(components["toolbox"], "multi_modal"):
            components["toolbox"].multi_modal.memory = components["memory"]
            logger.debug("[MultiModal] memory wired to multimodal handler")

        # ====================== 可选神经/代理 ======================
        components["sub_agent_manager"] = (
            SubAgentManager(components["router"], components["evolution_engine"])
            if SubAgentManager
            else None
        )
        components["sensory"] = (
            SensoryNervousSystem(components["bus"].publish) if SensoryNervousSystem else None
        )
        components["proprioception"] = (
            ProprioceptiveSystem(components["bus"].publish) if ProprioceptiveSystem else None
        )
        components["dlq"] = DeadLetterQueue() if DeadLetterQueue else None
        components["claw_hub"] = ClawHub(components["toolbox"]) if ClawHub else None
        components["meta_cortex"] = (
            MetaCortex(
                components["router"], components["memory"], components["evolution_engine"], None
            )
            if MetaCortex
            else None
        )
        components["self_model"] = SelfModel() if SelfModel else None

        from adami_kernel.guardian.sensitive_filter import SensitiveFilter

        components["sensitive_filter"] = SensitiveFilter()

        # ====================== Skill 系列 ======================
        components["vector_store"] = VectorStore(components["memory"])
        logger.debug("[ComponentInitializer] VectorStore created early")

        components["skill_router"] = SkillRouter(
            memory=components["memory"],
            llm_router=components["router"],
            evolution_engine=components["evolution_engine"],
        )
        if components["vector_store"]:
            components["skill_router"].set_vector_store(components["vector_store"])

        components["workflow_engine"] = WorkflowEngine(
            bus=components["bus"], memory=components["memory"], toolbox=components["toolbox"]
        )
        components["multi_agent_orchestrator"] = MultiAgentOrchestrator(
            bus=components["bus"], memory=components["memory"], toolbox=components["toolbox"]
        )
        components["reflexion_loop"] = ReflexionLoop(
            memory=components["memory"],
            episodic_memory=components["episodic_memory"],
            router=components["router"],
            bus=components["bus"],
        )
        components["tdd_evolution"] = TDDEvolution(
            evolution_engine=components["evolution_engine"],
            dream_sandbox=components["dream_sandbox"],
            memory=components["memory"],
            episodic_memory=components["episodic_memory"],
            proprioception=components["proprioception"],
            router=components["router"],
        )

        components["skill_composer"] = SkillComposer(
            router=components["router"],
            memory=components["memory"],
            toolbox=components["toolbox"],
            skill_router=components["skill_router"],
        )

        if components["dream_sandbox"] and components["router"]:
            components["skill_manager"] = SkillManager(
                memory=components["memory"],
                evolution_engine=components["evolution_engine"],
                dream_sandbox=components["dream_sandbox"],
                router=components["router"],
                vector_store=components["vector_store"],
            )
        else:
            components["skill_manager"] = None

        if components["memory"] and components["evolution_engine"]:
            components["skill_version_manager"] = SkillVersionManager(
                components["memory"], components["evolution_engine"]
            )
        else:
            components["skill_version_manager"] = None

        # ====================== SelfTestEngine 先创建（确保后续注入可用） ======================
        components["self_test_engine"] = SelfTestEngine(
            memory=components["memory"],
            bus=components["bus"],
            dream_sandbox=components["dream_sandbox"],
        )
        # =================================================================================

        if components["memory"] and components["evolution_engine"] and components["skill_manager"]:
            components["skill_cleaner"] = SkillCleaner(
                memory=components["memory"],
                evolution_engine=components["evolution_engine"],
                vector_store=components["vector_store"],
                skill_version_manager=components["skill_version_manager"],
            )
            # ====================== 【本次核心修复】SkillOptimizer 显式注入 SelfTestRunner ======================
            components["skill_optimizer"] = SkillOptimizer(
                memory=components["memory"],
                episodic_memory=components["episodic_memory"],
                evolution_engine=components["evolution_engine"],
                skill_manager=components["skill_manager"],
                router=components["router"],
                # 【修复】提取 engine 内部真实的 runner 实例注入，解决 no attribute 错误
                self_test_runner=components["self_test_engine"].runner
                if components.get("self_test_engine")
                else None,
            )
            # =================================================================================
            if components["skill_version_manager"] and components["skill_optimizer"]:
                components["skill_version_manager"].set_skill_optimizer(
                    components["skill_optimizer"]
                )
            if components["skill_manager"] and components["skill_optimizer"]:
                components["skill_manager"].set_skill_optimizer(components["skill_optimizer"])
        else:
            components["skill_cleaner"] = None
            components["skill_optimizer"] = None

        if components["skill_manager"] and components["vector_store"]:
            if hasattr(components["skill_manager"], "set_vector_store"):
                components["skill_manager"].set_vector_store(components["vector_store"])

        if components.get("evolution_engine") and components.get("skill_manager"):
            components["evolution_engine"].skill_manager = components["skill_manager"]
            components["evolution_engine"].file_loader.skill_manager = components["skill_manager"]

        if components.get("evolution_engine") and components.get("skill_optimizer"):
            cg = getattr(components["evolution_engine"], "code_generator", None)
            if cg is not None:
                cg.skill_optimizer = components["skill_optimizer"]

        components["planner"] = TaskPlanner(
            router=components["router"],
            evolution_engine=components["evolution_engine"],
            bus=components["bus"],
            sensitive_filter=components["sensitive_filter"],
            episodic_memory=components["episodic_memory"],
            memory=components["memory"],
            workflow_engine=components["workflow_engine"],
            multi_agent_orchestrator=components["multi_agent_orchestrator"],
            reflexion_loop=components["reflexion_loop"],
            tdd_evolution=components["tdd_evolution"],
            skill_composer=components["skill_composer"],
            skill_router=components["skill_router"],
            second_brain=components.get("second_brain"),
        )

        components["observability"] = observability
        if hitl_handler_module.hitl_handler is None:
            hitl_handler_module.hitl_handler = HitlHandler(
                components["bus"],
                telegram_nerve=None,
                workflow_engine=components.get("workflow_engine"),
            )
        components["hitl_handler"] = hitl_handler_module.hitl_handler
        components["multi_tenant_guard"] = multi_tenant_guard

        components["intent_router"] = (
            SemanticIntentRouter(components["router"]) if SemanticIntentRouter else None
        )

        # ====================== Intent adaptive — template registry (Step 5; default no-op entries) ====
        from adami_kernel.cortex.intent_adaptive.bootstrap_templates import (
            register_builtin_intent_templates,
        )
        from adami_kernel.cortex.intent_adaptive.models import IntentType as _IntentTypeWire
        from adami_kernel.cortex.intent_adaptive.template_registry import (
            NoOpTemplateHandler,
            TemplateRegistry,
        )

        _intent_templates = TemplateRegistry(min_match_score=0.0)
        _intent_templates.register(str(_IntentTypeWire.UNKNOWN), NoOpTemplateHandler())
        register_builtin_intent_templates(_intent_templates)
        components["intent_template_registry"] = _intent_templates
        logger.debug(
            "[ComponentInitializer] intent_template_registry ready (built-in templates + noop)"
        )

        # ====================== NerveRegistry ======================
        components["nerve_registry"] = NerveRegistry()
        logger.debug("[ComponentInitializer] NerveRegistry: registering default nerves")
        components["nerve_registry"].register_default_nerves(components["bus"].publish)

        components["discord_nerve"] = components["nerve_registry"].get_nerve_by_platform("discord")
        components["telegram_nerve"] = components["nerve_registry"].get_nerve_by_platform(
            "telegram"
        )

        # ====================== 【本次修复】hitl_handler TelegramNerve 注入 ======================
        if components.get("telegram_nerve") and hitl_handler_module.hitl_handler is not None:
            hitl_handler_module.hitl_handler.set_telegram_nerve(components["telegram_nerve"])
            logger.debug("[ComponentInitializer] HitlHandler telegram nerve set")
        # =================================================================================

        n_nerves = len(components["nerve_registry"].nerves)
        if n_nerves:
            logger.info(boot_t("boot.log.component_nerve_registry", n=n_nerves))

        # ====================== 【关键修复】SkillMarket / GitHubHunter + health_server ======================
        components["skill_market"] = SkillMarket(
            evolution_engine=components["evolution_engine"],
            meta_cortex=components["meta_cortex"],
            router=components["router"],
        )
        components["github_hunter"] = GitHubHunter(components["router"])

        # 确保 health_server 始终存在（解决 KeyError）
        if "health_server" not in components:
            components["health_server"] = HealthServer(None)
        logger.debug("[ComponentInitializer] HealthServer attached")
        # =================================================================================

        from adami_kernel.orchestrator.evolution_orchestrator import EvolutionOrchestrator

        components["evolution_orchestrator"] = EvolutionOrchestrator(
            meta_cortex=components["meta_cortex"],
            skill_market=components["skill_market"],
            github_hunter=components["github_hunter"],
            self_test_engine=components["self_test_engine"],
            evolution_engine=components["evolution_engine"],
            memory=components["memory"],
            router=components["router"],
        )

        components["base_persona"] = boot_t("cjk_gate.default_base_persona")

        components["policy_loader"] = PolicyLoader.from_settings()
        set_policy_loader(components["policy_loader"])

        components["prompt_builder"] = PromptBuilder(
            system_persona=components["base_persona"],
            second_brain=components["second_brain"],
            policy_loader=components["policy_loader"],
        )

        components["fitness_evaluator"] = FitnessEvaluator()

        components["circadian_nerve"] = CircadianNerve(components["bus"])
        components["report_scheduler"] = ReportScheduler(components["bus"])
        components["registry"] = PluginRegistry()

        for name, inst in components.items():
            if inst is not None and name not in [
                "base_persona",
                "prompt_builder",
                "policy_loader",
                "fitness_evaluator",
            ]:
                components["registry"].register(name, inst)

        # ====================== 全局同步（仅保留 kernel 赋值，供 app.state 使用） ======================
        if kernel is not None:
            kernel.skill_market = components.get("skill_market")
            kernel.github_hunter = components.get("github_hunter")
            logger.debug("[ComponentInitializer] SkillMarket / GitHubHunter on kernel")
        else:
            logger.warning(boot_t("boot.log.component_kernel_none"))

        logger.info(boot_t("boot.log.component_init_all", count=len(components)))
        return components


# --- END OF FILE component_initializer.py ---
# 文件路径：src/adami_kernel/core/component_initializer.py
