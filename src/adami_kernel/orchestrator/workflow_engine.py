# --- START OF FILE workflow_engine.py ---

import asyncio
import logging
import re
import time
from typing import Any, Dict, Optional

from adami_kernel.config import settings
from adami_kernel.cortex.tools_manager import ToolboxManager
from adami_kernel.guardian.immunity import ImmunitySystem
from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.i18n import t
from adami_kernel.integration.deer_flow_bridge import (
    deer_flow_delegate_enabled_for_execution,
    execute_delegate_deerflow_node,
)
from adami_kernel.nexus.bus import EventBus
from adami_kernel.nexus.event import AdamiEvent, EventPriority
from adami_kernel.orchestrator.long_task_failure_policy import classify_workflow_node_failure
from adami_kernel.orchestrator.long_task_phase_gate import (
    LongTaskPhase,
    checkpoint_hitl_boundary,
    emit_phase_transition_if_changed,
    long_task_phase_for_workflow_node,
)
from adami_kernel.orchestrator.long_task_recovery import (
    apply_replay_from_phase_checkpoint,
    failure_audit_record,
    rollback_to_last_good_checkpoint,
)
from adami_kernel.orchestrator.long_task_sandbox import (
    run_isolated_tool_command,
    stage_artifact_for_sandbox_run,
)
from adami_kernel.orchestrator.long_task_schema import (
    append_stage_artifact,
    is_long_task_tracking_enabled,
    maybe_initialize_long_task_context,
)
from adami_kernel.orchestrator.multi_tenant_guard import multi_tenant_guard
from adami_kernel.orchestrator.workflow_models import (
    Node,
    WorkflowState,
    create_initial_workflow_state,
)
from adami_kernel.telemetry.experience_sink import (
    experience_episode_id_ctx,
    experience_primary_trace_ctx,
    get_experience_sink,
    infer_tool_audit_meta,
    redact_payload,
    summarize_text,
)

# ====================== 【阶段4 集成】Observability + Multi-Tenant ======================
from adami_kernel.web.observability import observability

# =================================================================================

logger = logging.getLogger("AdamI-WorkflowEngine")


def _wfe_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


def _workflow_node_timeout_sec(node: Node, *, kind: str = "default") -> float:
    """Immunity 超时（秒）：与 Node.timeout 及配置保底取较大值，避免 LLM/构建被过短默认值误杀。"""
    base = (
        int(node.timeout)
        if getattr(node, "timeout", None)
        else int(settings.ADAMI_WORKFLOW_NODE_DEFAULT_TIMEOUT_SEC)
    )
    if kind == "llm":
        floor = int(getattr(settings, "ADAMI_WORKFLOW_LLM_NODE_TIMEOUT", 300))
        return float(max(base, floor))
    if kind == "skill_build":
        floor = int(getattr(settings, "ADAMI_WORKFLOW_SKILL_BUILD_TIMEOUT", 300))
        return float(max(base, floor))
    floor = int(getattr(settings, "ADAMI_SKILL_TIMEOUT", 60))
    return float(max(base, floor))


class WorkflowEngine:
    """
    AdamI 2.0 工作流引擎（工业级轻量状态机）
    核心功能：持久化、可暂停、可恢复、多步执行、自动重试、检查点
    已集成阶段4：Observability Span、HITL、chat_id 多租户隔离、幂等性检查、条件分支
    【本次核心修复】：移除 release_lock 的错误 await 调用，增加判空保护
    【步骤4】SkillComposer DAG：经 workflow.events / WORKFLOW_START 驱动执行 + completion Future 收口
    """

    def __init__(self, bus: EventBus, memory: LayeredMemory, toolbox: ToolboxManager):
        self.bus = bus
        self.memory = memory
        self.toolbox = toolbox
        self.immunity = ImmunitySystem()
        self.reflexion_loop = None  # kernel.py boot() 时注入
        self.evolution_engine = None  # BootManager 注入；SKILL_CALL 必需

        # 内存缓存（加速访问）
        self.active_workflows: Dict[str, WorkflowState] = {}
        self._completion_futures: Dict[str, asyncio.Future] = {}
        self._workflow_start_scheduled: set[str] = set()

        # 订阅工作流事件
        self._subscription_task = None
        self._workflow_events_q: Optional[asyncio.Queue] = None
        self._run_tasks: set[asyncio.Task] = set()
        logger.info(_wfe_t("wfe.log.ready"))

    def set_evolution_engine(self, evolution_engine: Any) -> None:
        self.evolution_engine = evolution_engine
        logger.debug(_wfe_t("wfe.debug.ev_set"))

    def _find_entry_node(self, state: WorkflowState) -> str:
        all_ids = set(state.nodes.keys())
        incoming: set[str] = set()
        for outs in state.edges.values():
            for t in outs:
                incoming.add(t)
        starts = sorted(all_ids - incoming)
        if starts:
            return starts[0]
        return sorted(all_ids)[0]

    def _resolve_string_template(self, template: str, context: Dict[str, Any]) -> str:
        if not template:
            return ""

        def replacer(match: re.Match) -> str:
            path = match.group(1)
            parts = path.split(".")
            val: Any = context
            for part in parts:
                if isinstance(val, dict):
                    val = val.get(part)
                else:
                    val = None
                    break
            return "" if val is None else str(val)

        return re.sub(r"\$context\.([a-zA-Z0-9_.]+)", replacer, template)

    def _resolve_skill_args(self, args_spec: Any, context: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(args_spec, dict):
            return {}
        out: Dict[str, Any] = {}
        for k, v in args_spec.items():
            if isinstance(v, str) and v.startswith("$context."):
                path = v[len("$context.") :]
                parts = path.split(".")
                val: Any = context
                for part in parts:
                    if isinstance(val, dict):
                        val = val.get(part)
                    else:
                        val = None
                        break
                out[k] = val
            elif isinstance(v, dict):
                out[k] = self._resolve_skill_args(v, context)
            else:
                out[k] = v
        return out

    def _try_complete_workflow_future(
        self, state: WorkflowState, exc: Optional[BaseException] = None
    ):
        self._workflow_start_scheduled.discard(state.workflow_id)
        fut = self._completion_futures.pop(state.workflow_id, None)
        if fut is None or fut.done():
            return
        if exc is not None:
            fut.set_exception(exc)
        else:
            fut.set_result(state.context)

    async def prepare_composed_workflow_for_bus(self, state: WorkflowState) -> asyncio.Future:
        """注册已 compose 的 WorkflowState：持久化、登记 completion Future。须再发布 WORKFLOW_START 方开始执行。"""
        if multi_tenant_guard:
            await multi_tenant_guard.validate_chat_id(state.chat_id)

        state.status = "RUNNING"
        state.current_node_id = self._find_entry_node(state)
        maybe_initialize_long_task_context(state)
        for nid, n in state.nodes.items():
            if (
                n.node_type == "DELEGATE_DEERFLOW"
                and not deer_flow_delegate_enabled_for_execution()
            ):
                raise RuntimeError(_wfe_t("wfe.error.deerflow_node_disabled", node_id=nid))
        await self.memory.save_workflow_state(state)
        self.active_workflows[state.workflow_id] = state

        get_experience_sink().begin_episode(
            state.workflow_id,
            state.workflow_id,
            push_context=False,
            source="workflow_engine.prepare_composed",
            chat_id=str(state.chat_id),
        )

        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._completion_futures[state.workflow_id] = fut
        logger.info(
            _wfe_t(
                "wfe.log.compose_reg",
                wid=state.workflow_id,
                entry=state.current_node_id,
            )
        )
        return fut

    async def _emit_workflow_start(
        self, state: WorkflowState, *, source_module: str = "workflow.engine"
    ) -> None:
        await self.bus.publish(
            AdamiEvent(
                trace_id=f"wf_start_{state.workflow_id}",
                source_module=source_module,
                target_topic="workflow.events",
                priority=EventPriority.NORMAL,
                payload={
                    "workflow_id": state.workflow_id,
                    "event_type": "WORKFLOW_START",
                    "chat_id": state.chat_id,
                },
            )
        )

    async def run_composed_state(self, state: WorkflowState) -> asyncio.Future:
        """兼容入口：注册 composed 状态并由本模块发布 WORKFLOW_START（与 Planner 直发事件等价）。"""
        fut = await self.prepare_composed_workflow_for_bus(state)
        await self._emit_workflow_start(state)
        return fut

    async def initialize(self):
        """启动工作流引擎，订阅 EventBus"""
        # Subscribe synchronously to avoid dropping system events published before the listener
        # gets a chance to call `bus.subscribe`.
        if self._workflow_events_q is None:
            self._workflow_events_q = await self.bus.subscribe("workflow.events")
        if self._subscription_task is None or self._subscription_task.done():
            self._subscription_task = asyncio.create_task(self._listen_workflow_events())
        logger.debug(_wfe_t("wfe.debug.subscribed"))

    async def _listen_workflow_events(self):
        """监听工作流事件，推动状态机前进"""
        q = self._workflow_events_q or (await self.bus.subscribe("workflow.events"))
        while True:
            try:
                event: AdamiEvent = await asyncio.wait_for(
                    q.get(), timeout=float(settings.ADAMI_ORCHESTRATOR_QUEUE_POLL_SEC)
                )
                if event.target_topic == "workflow.events":
                    await self._handle_workflow_event(event)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(_wfe_t("wfe.err.listen", e=e), exc_info=True)

    async def _handle_workflow_event(self, event: AdamiEvent):
        """处理工作流事件"""
        payload = event.payload
        workflow_id = payload.get("workflow_id")
        if not workflow_id:
            return

        event_type = payload.get("event_type")
        node_id = payload.get("node_id")

        # 阶段4 多租户校验
        chat_id = payload.get("chat_id")
        if multi_tenant_guard:
            await multi_tenant_guard.validate_chat_id(chat_id)

        state = await self.memory.get_workflow_state(workflow_id, chat_id)
        if not state:
            # Fallback: for hot workflows (or transient persistence errors), consult in-memory cache.
            state = self.active_workflows.get(str(workflow_id))
        if not state:
            logger.warning(_wfe_t("wfe.warn.state_missing", wid=workflow_id))
            return

        if event_type == "NODE_COMPLETE":
            await self._route_next(state, node_id, payload.get("result"))
        elif event_type == "NODE_FAILED":
            await self._handle_node_failure(state, node_id, payload.get("error"))
        elif event_type == "HITL_RESUME":
            await self.resume_workflow(workflow_id, payload.get("user_input"))
        elif event_type == "WORKFLOW_START":
            if workflow_id in self._workflow_start_scheduled:
                logger.debug(_wfe_t("wfe.debug.start_dup", wid=workflow_id))
                return
            self._workflow_start_scheduled.add(workflow_id)
            state.status = "RUNNING"
            if not state.current_node_id:
                state.current_node_id = self._find_entry_node(state)
            self.active_workflows[state.workflow_id] = state
            await self.memory.save_workflow_state(state)
            t = asyncio.create_task(self._execute_node(state))
            self._run_tasks.add(t)
            t.add_done_callback(lambda _t: self._run_tasks.discard(_t))

    # ====================== 核心工作流方法 ======================
    async def start_workflow(self, chat_id: str, task_description: str) -> str:
        """创建并启动一个新工作流（带锁保护）"""
        if multi_tenant_guard:
            await multi_tenant_guard.validate_chat_id(chat_id)

        state = create_initial_workflow_state(chat_id=chat_id, task_description=task_description)
        state.status = "RUNNING"
        state.current_node_id = "__start__"

        lock_key = f"wf_{state.workflow_id}"
        if multi_tenant_guard:
            await multi_tenant_guard.acquire_lock(lock_key, chat_id)
        try:
            await self.memory.save_workflow_state(state)
            self.active_workflows[state.workflow_id] = state
            get_experience_sink().begin_episode(
                state.workflow_id,
                state.workflow_id,
                push_context=False,
                source="workflow_engine.start_workflow",
                chat_id=str(chat_id),
            )
            asyncio.create_task(self._execute_node(state))

            logger.debug(_wfe_t("wfe.debug.wf_started", wid=state.workflow_id))
            return state.workflow_id
        finally:
            if multi_tenant_guard:
                multi_tenant_guard.release_lock(lock_key, chat_id)  # 移除 await

    async def _execute_node(self, state: WorkflowState):
        """执行当前节点（集成 Observability + HITL + 幂等性检查 + 锁保护）"""
        node_id = state.current_node_id
        if not node_id or node_id not in state.nodes:
            return

        if state.global_step_count >= state.max_steps:
            state.status = "FAILED"
            await self.memory.save_workflow_state(state)
            get_experience_sink().end_episode(
                state.workflow_id,
                "failed",
                pop_context=False,
                extra_meta={"reason": "max_steps"},
            )
            self._try_complete_workflow_future(
                state, RuntimeError(_wfe_t("wfe.error.max_steps", max_steps=state.max_steps))
            )
            logger.error(_wfe_t("wfe.err.max_steps_log", wid=state.workflow_id))
            return

        # ========== 幂等性检查 ==========
        for record in state.history:
            if record.get("node_id") == node_id and record.get("status") == "SUCCESS":
                logger.debug(_wfe_t("wfe.debug.node_skip", nid=node_id))
                await self._route_next(state, node_id, record.get("result"))
                return
        # ================================================

        # ========== MultiTenantGuard 锁保护 ==========
        lock_key = f"wf_{state.workflow_id}"
        if multi_tenant_guard:
            await multi_tenant_guard.acquire_lock(lock_key, state.chat_id)
        tok_e = experience_episode_id_ctx.set(state.workflow_id)
        tok_p = experience_primary_trace_ctx.set(state.workflow_id)
        try:
            node = state.nodes[node_id]
            logger.debug(_wfe_t("wfe.debug.exec_node", nid=node_id, ntype=node.node_type))

            # ====================== 【阶段4】Observability Span ======================
            async with observability.start_span(
                span_name=f"workflow.node.execute.{node.node_type}",
                workflow_id=state.workflow_id,
                node_id=node_id,
                chat_id=state.chat_id,
                attributes={"timeout": node.timeout, "max_retries": node.max_retries},
            ):
                try:
                    # ====================== 【阶段4】HITL 高危动作检测 ======================
                    if await self._is_high_risk_action(node):
                        await checkpoint_hitl_boundary(
                            state,
                            self.memory,
                            self.bus,
                            kind="pre_hitl_pause",
                            node_id=node_id,
                            reason="high_risk_hitl",
                            source_module="workflow.engine",
                        )
                        state.status = "PAUSED"
                        await self.memory.save_workflow_state(state)

                        pause_event = AdamiEvent(
                            trace_id=f"wf_pause_{node_id}",
                            source_module="workflow.engine",
                            target_topic="hitl.events",
                            priority=EventPriority.HIGH,
                            payload={
                                "workflow_id": state.workflow_id,
                                "chat_id": state.chat_id,
                                "reason": t(
                                    "orch.hitl.reason_high_risk_node",
                                    node_id=node_id,
                                    locale=settings.effective_ui_default_locale(),
                                ),
                            },
                        )
                        await self.bus.publish(pause_event)
                        logger.debug(_wfe_t("wfe.debug.hitl_pause", wid=state.workflow_id))
                        return
                    # =====================================================================

                    # 使用 Immunity 包装超时保护
                    if node.node_type in ("START", "END", "HUMAN"):
                        result = {
                            "status": "success",
                            "data": _wfe_t("wfe.msg.simple_node_passed", node_type=node.node_type),
                        }
                    elif node.node_type == "TOOL":
                        cmd = node.config.get("command", "") or ""
                        t_sec = _workflow_node_timeout_sec(node, kind="default")
                        if (
                            is_long_task_tracking_enabled(state)
                            and getattr(settings, "ADAMI_LONG_TASK_ISOLATED_TOOL_RUN", True)
                            and not node.config.get("long_task_disable_isolated_run")
                        ):

                            async def _iso_tool():
                                return await run_isolated_tool_command(
                                    self.toolbox,
                                    cmd,
                                    workflow_id=state.workflow_id,
                                    timeout=float(t_sec),
                                )

                            result, sand_handle = await self.immunity.run_with_timeout(
                                _iso_tool(), timeout=t_sec
                            )
                            try:
                                append_stage_artifact(
                                    state,
                                    stage_artifact_for_sandbox_run(
                                        sand_handle,
                                        command=cmd,
                                        set_phase_test="pytest" in cmd.lower(),
                                    ),
                                    set_current_phase=False,
                                )
                            except Exception as art_e:
                                logger.warning(
                                    _wfe_t("wfe.warn.sandbox_art", e=art_e),
                                )
                        else:
                            result = await self.immunity.run_with_timeout(
                                self.toolbox.execute_command(cmd),
                                timeout=t_sec,
                            )
                        if not isinstance(result, dict):
                            result = {"status": "success", "data": result}
                    elif node.node_type == "DELEGATE_DEERFLOW":
                        if not deer_flow_delegate_enabled_for_execution():
                            raise RuntimeError(_wfe_t("wfe.error.deerflow_requires_flag"))
                        t_sec = max(
                            float(_workflow_node_timeout_sec(node, kind="default")),
                            float(getattr(settings, "ADAMI_DEERFLOW_POLL_TIMEOUT_SEC", 3600.0)),
                        )

                        async def _delegate_df():
                            return await execute_delegate_deerflow_node(
                                memory=self.memory,
                                state=state,
                                node_id=node_id,
                                resolve_prompt=lambda tpl: self._resolve_string_template(
                                    tpl, state.context
                                ),
                                poll_timeout_sec=t_sec,
                            )

                        result = await self.immunity.run_with_timeout(_delegate_df(), timeout=t_sec)
                        if not isinstance(result, dict):
                            result = {"status": "success", "data": result}
                    elif node.node_type in ("LLM", "LLM_CALL"):
                        router = getattr(self.toolbox, "router", None)
                        if not router:
                            raise RuntimeError(_wfe_t("wfe.error.router_missing"))
                        prompt_t = node.config.get("prompt", "")
                        prompt = self._resolve_string_template(prompt_t, state.context)
                        brain_type = node.config.get("brain_type", "think")
                        temperature = float(node.config.get("temperature", 0.3))
                        text = await self.immunity.run_with_timeout(
                            router.call_llm(prompt, brain_type=brain_type, temperature=temperature),
                            timeout=_workflow_node_timeout_sec(node, kind="llm"),
                        )
                        state.context[node_id] = {"response": text}
                        await self.memory.save_workflow_state(state)
                        result = {"status": "success", "data": text}
                    elif node.node_type == "SKILL_CALL":
                        ee = self.evolution_engine
                        if not ee:
                            raise RuntimeError(_wfe_t("wfe.error.evolution_missing"))
                        skill_name = (node.config.get("skill_name") or "").strip()
                        raw_args = node.config.get("args", {}) or {}
                        args = self._resolve_skill_args(raw_args, state.context)
                        code = args.get("code") or state.context.get("extracted_code") or ""
                        if skill_name in ("__TEMP__", "", "TEMP") and code:
                            sn = ee.sanitize_skill_name(
                                args.get("skill_name_out")
                                or state.context.get("proposed_skill_name")
                                or f"WF_{state.workflow_id[:8]}"
                            )

                            async def _build_and_load_temp_skill():
                                fp, vr = await ee.skill_builder.build(code, sn)
                                if not vr.passed or not fp:
                                    raise RuntimeError(
                                        _wfe_t("wfe.error.skill_build_failed", detail=str(vr))
                                    )
                                await ee.file_loader.load_from_directory(
                                    ee.skills_dir, is_instinct=False
                                )
                                return fp, vr

                            t_skill = time.perf_counter()
                            file_path, validation_result = await self.immunity.run_with_timeout(
                                _build_and_load_temp_skill(),
                                timeout=_workflow_node_timeout_sec(node, kind="skill_build"),
                            )
                            temp_latency_ms = (time.perf_counter() - t_skill) * 1000
                            result = {
                                "status": "success",
                                "data": {
                                    "message": _wfe_t(
                                        "wfe.msg.skill_built_from_workflow", skill_name=sn
                                    ),
                                    "skill_path": file_path,
                                    "skill_name": sn,
                                },
                            }
                            meta_sn = infer_tool_audit_meta(ee, str(sn), override_backend="native")
                            get_experience_sink().record_tool_call(
                                trace_id=f"wf_{state.workflow_id}_{node_id}",
                                episode_id=state.workflow_id,
                                tool_name=str(sn),
                                tool_id=meta_sn["tool_id"],
                                args_summary=summarize_text(str(redact_payload(args))[:2000]),
                                result_summary=summarize_text(str(redact_payload(result))[:2000]),
                                ok=True,
                                tool_backend=meta_sn["tool_backend"],
                                latency_ms=temp_latency_ms,
                                docker_used=meta_sn["docker_used"],
                                mcp_allow_deny=meta_sn["mcp_allow_deny"],
                                extra={
                                    "node_id": node_id,
                                    "skill_build": "temp",
                                    "path": "workflow_engine.SKILL_CALL",
                                },
                            )
                        else:
                            skill_fn = ee.get_skill(skill_name)
                            if not skill_fn:
                                raise RuntimeError(
                                    _wfe_t("wfe.error.skill_missing", skill_name=skill_name)
                                )
                            exec_coro = (
                                skill_fn(**args)
                                if asyncio.iscoroutinefunction(skill_fn)
                                else asyncio.to_thread(skill_fn, **args)
                            )
                            t_skill = time.perf_counter()
                            exec_res = await self.immunity.run_with_timeout(
                                exec_coro,
                                timeout=_workflow_node_timeout_sec(node, kind="default"),
                            )
                            skill_latency_ms = (time.perf_counter() - t_skill) * 1000
                            if isinstance(exec_res, dict):
                                result = exec_res
                            else:
                                result = {"status": "success", "data": exec_res}
                            meta_wf = infer_tool_audit_meta(ee, str(skill_name))
                            get_experience_sink().record_tool_call(
                                trace_id=f"wf_{state.workflow_id}_{node_id}",
                                episode_id=state.workflow_id,
                                tool_name=str(skill_name),
                                tool_id=meta_wf["tool_id"],
                                args_summary=summarize_text(str(redact_payload(args))[:2000]),
                                result_summary=summarize_text(str(redact_payload(result))[:2000]),
                                ok=True,
                                tool_backend=meta_wf["tool_backend"],
                                latency_ms=skill_latency_ms,
                                docker_used=meta_wf["docker_used"],
                                mcp_allow_deny=meta_wf["mcp_allow_deny"],
                                extra={"node_id": node_id, "path": "workflow_engine.SKILL_CALL"},
                            )
                        state.context[node_id] = result
                        await self.memory.save_workflow_state(state)
                    elif node.node_type == "CONDITION":
                        condition_template = node.config.get("condition", "")

                        def safe_get(path: str):
                            keys = path.split(".")
                            val = state.context
                            for k in keys:
                                if isinstance(val, dict) and k in val:
                                    val = val[k]
                                else:
                                    return None
                            return val

                        try:
                            match = re.match(
                                r"^\$context\.([a-zA-Z0-9_.]+)\s*(==|!=|>|>=|<|<=)\s*(.+)$",
                                condition_template.strip(),
                            )
                            if not match:
                                raise ValueError(
                                    _wfe_t(
                                        "wfe.error.invalid_condition",
                                        condition_template=condition_template,
                                    )
                                )
                            var_path, operator, right_operand = match.groups()
                            left_val = safe_get(var_path)
                            right_operand = right_operand.strip().strip("'").strip('"')
                            if right_operand.lower() == "true":
                                right_val = True
                            elif right_operand.lower() == "false":
                                right_val = False
                            elif right_operand.isdigit():
                                right_val = int(right_operand)
                            else:
                                right_val = right_operand
                            cond_result = False
                            if operator == "==":
                                cond_result = str(left_val) == str(right_val)
                            elif operator == "!=":
                                cond_result = str(left_val) != str(right_val)
                            elif operator == ">":
                                cond_result = (
                                    float(left_val) > float(right_val)
                                    if left_val is not None
                                    else False
                                )
                            elif operator == ">=":
                                cond_result = (
                                    float(left_val) >= float(right_val)
                                    if left_val is not None
                                    else False
                                )
                            elif operator == "<":
                                cond_result = (
                                    float(left_val) < float(right_val)
                                    if left_val is not None
                                    else False
                                )
                            elif operator == "<=":
                                cond_result = (
                                    float(left_val) <= float(right_val)
                                    if left_val is not None
                                    else False
                                )
                        except Exception as cond_err:
                            logger.error(_wfe_t("wfe.err.cond_eval", e=cond_err))
                            cond_result = False

                        def _clean_branch_id(v: object) -> Optional[str]:
                            if v is None:
                                return None
                            s = str(v).strip()
                            return s if s else None

                        true_next = _clean_branch_id(node.config.get("true_next"))
                        false_next = _clean_branch_id(node.config.get("false_next"))
                        static_edges = list(state.edges.get(node_id) or [])

                        if cond_result and true_next:
                            state.edges[node_id] = [true_next]
                        elif not cond_result and false_next:
                            state.edges[node_id] = [false_next]
                        elif cond_result and not true_next and false_next:
                            logger.warning(
                                _wfe_t(
                                    "wfe.warn.condition_missing_true",
                                    node_id=node_id,
                                    fallback=false_next,
                                )
                            )
                            state.edges[node_id] = [false_next]
                        elif not cond_result and not false_next and true_next:
                            logger.warning(
                                _wfe_t(
                                    "wfe.warn.condition_missing_false",
                                    node_id=node_id,
                                    fallback=true_next,
                                )
                            )
                            state.edges[node_id] = [true_next]
                        elif static_edges:
                            if len(static_edges) >= 2:
                                pick = static_edges[0] if cond_result else static_edges[1]
                            else:
                                pick = static_edges[0]
                            logger.warning(
                                _wfe_t(
                                    "wfe.warn.condition_static_fallback",
                                    node_id=node_id,
                                    nxt=pick,
                                )
                            )
                            state.edges[node_id] = [pick]
                        elif true_next or false_next:
                            pick = true_next or false_next
                            logger.warning(
                                _wfe_t(
                                    "wfe.warn.condition_single_branch",
                                    node_id=node_id,
                                    nxt=pick,
                                )
                            )
                            state.edges[node_id] = [pick]
                        else:
                            logger.warning(_wfe_t("wfe.warn.condition_terminal", node_id=node_id))
                            state.edges[node_id] = []
                        state.context[node_id] = {"condition_result": cond_result}
                        await self.memory.save_workflow_state(state)
                        result = {"status": "success", "data": cond_result}
                    else:
                        result = {
                            "status": "success",
                            "data": _wfe_t("wfe.msg.node_done", node_id=node_id),
                        }

                    # 发布完成事件
                    event = AdamiEvent(
                        trace_id=f"wf_node_{node_id}",
                        source_module="workflow.engine",
                        target_topic="workflow.events",
                        priority=EventPriority.NORMAL,
                        payload={
                            "workflow_id": state.workflow_id,
                            "node_id": node_id,
                            "event_type": "NODE_COMPLETE",
                            "result": result,
                            "chat_id": state.chat_id,
                        },
                    )
                    await self.bus.publish(event)

                except Exception as e:
                    logger.error(_wfe_t("wfe.err.node_exec", nid=node_id, e=e))
                    if node.node_type == "SKILL_CALL":
                        ee2 = self.evolution_engine
                        snf = str(node.config.get("skill_name") or "unknown")
                        meta_f = (
                            infer_tool_audit_meta(ee2, snf)
                            if ee2
                            else {
                                "tool_id": snf.upper(),
                                "tool_backend": "native",
                                "docker_used": False,
                                "mcp_allow_deny": "n/a",
                            }
                        )
                        get_experience_sink().record_tool_call(
                            trace_id=f"wf_{state.workflow_id}_{node_id}",
                            episode_id=state.workflow_id,
                            tool_name=snf,
                            tool_id=meta_f["tool_id"],
                            args_summary=summarize_text(
                                str(redact_payload(node.config.get("args", {})))[:2000]
                            ),
                            result_summary="",
                            ok=False,
                            error_code=type(e).__name__,
                            tool_backend=meta_f["tool_backend"],
                            docker_used=meta_f["docker_used"],
                            mcp_allow_deny=meta_f["mcp_allow_deny"],
                            extra={"node_id": node_id, "path": "workflow_engine.SKILL_CALL"},
                        )
                    event = AdamiEvent(
                        trace_id=f"wf_node_{node_id}",
                        source_module="workflow.engine",
                        target_topic="workflow.events",
                        priority=EventPriority.HIGH,
                        payload={
                            "workflow_id": state.workflow_id,
                            "node_id": node_id,
                            "event_type": "NODE_FAILED",
                            "error": str(e),
                            "chat_id": state.chat_id,
                        },
                    )
                    await self.bus.publish(event)
        finally:
            experience_episode_id_ctx.reset(tok_e)
            experience_primary_trace_ctx.reset(tok_p)
            if multi_tenant_guard:
                multi_tenant_guard.release_lock(lock_key, state.chat_id)  # 移除 await

    async def _route_next(self, state: WorkflowState, current_node_id: str, result: Any):
        """根据 edges 路由到下一个节点（支持条件分支 + 锁保护）"""
        lock_key = f"wf_{state.workflow_id}"
        if multi_tenant_guard:
            await multi_tenant_guard.acquire_lock(lock_key, state.chat_id)
        try:
            next_node_id = None

            if isinstance(result, dict) and "next_node" in result:
                next_node_id = result["next_node"]
                logger.debug(
                    _wfe_t(
                        "wfe.debug.next_explicit",
                        cur=current_node_id,
                        nxt=next_node_id,
                    )
                )

            if not next_node_id:
                next_nodes = state.edges.get(current_node_id, [])
                if not next_nodes:
                    await emit_phase_transition_if_changed(
                        state,
                        self.memory,
                        self.bus,
                        to_phase=LongTaskPhase.DELIVER,
                        reason="dag_terminal_success",
                        source_module="workflow.engine",
                        gate_detail="workflow_terminal",
                        history_extras={
                            "completed_node_id": current_node_id,
                            "next_node_id": None,
                        },
                    )
                    state.status = "SUCCESS"
                    await self.memory.save_workflow_state(state)
                    logger.info(_wfe_t("wfe.log.wf_done", wid=state.workflow_id))
                    get_experience_sink().end_episode(
                        state.workflow_id, "success", pop_context=False
                    )
                    self._try_complete_workflow_future(state)
                    return
                next_node_id = next_nodes[0]

            nxt = state.nodes.get(next_node_id)
            if nxt is not None:
                await emit_phase_transition_if_changed(
                    state,
                    self.memory,
                    self.bus,
                    to_phase=long_task_phase_for_workflow_node(nxt),
                    reason=f"route_to_node {next_node_id}",
                    source_module="workflow.engine",
                    gate_detail="dag_route",
                    history_extras={
                        "completed_node_id": current_node_id,
                        "next_node_id": next_node_id,
                    },
                )

            state.current_node_id = next_node_id
            state.global_step_count += 1

            await self.memory.save_workflow_state(state)
            asyncio.create_task(self._execute_node(state))
        finally:
            if multi_tenant_guard:
                multi_tenant_guard.release_lock(lock_key, state.chat_id)  # 移除 await

    async def _handle_node_failure(self, state: WorkflowState, node_id: str, error: str):
        """节点失败：transient 走 max_retries；phase_fatal 优先 last_good 回滚（有次数上限）。"""
        lock_key = f"wf_{state.workflow_id}"
        if multi_tenant_guard:
            await multi_tenant_guard.acquire_lock(lock_key, state.chat_id)
        try:
            node = state.nodes.get(node_id)
            if not node:
                return
            err_s = error or ""
            fclass = classify_workflow_node_failure(node, err_s)
            max_rec = int(getattr(settings, "ADAMI_WORKFLOW_PHASE_RECOVERY_MAX", 2))

            if fclass == "phase_fatal":
                state.history.append(
                    failure_audit_record(
                        node_id=node_id,
                        error=err_s,
                        failure_class="phase_fatal",
                        retries_at_failure=state.error_retry_counts.get(node_id, 0),
                        recovery_action="attempt_rollback",
                    )
                )
                try:
                    await self.memory.record_checkpoint_failure(
                        state.workflow_id,
                        failed_phase=str(state.context.get("current_phase") or "unknown"),
                        message=err_s[:1500],
                        workflow_state_version=state.version,
                    )
                except Exception as ex:
                    logger.warning(_wfe_t("wfe.warn.ckpt_rec_fail", e=ex))
                used = int(state.metadata.get("phase_recovery_count", 0))
                if used < max_rec and await rollback_to_last_good_checkpoint(state, self.memory):
                    state.metadata["phase_recovery_count"] = used + 1
                    state.error_retry_counts[node_id] = 0
                    state.status = "RUNNING"
                    await self.memory.save_workflow_state(state)
                    logger.warning(
                        _wfe_t(
                            "wfe.warn.phase_rollback",
                            wid=state.workflow_id,
                            nid=node_id,
                            used=used + 1,
                            maxr=max_rec,
                        ),
                    )
                    asyncio.create_task(self._execute_node(state))
                    return
                state.history.append(
                    failure_audit_record(
                        node_id=node_id,
                        error=err_s,
                        failure_class="phase_fatal",
                        retries_at_failure=state.error_retry_counts.get(node_id, 0),
                        recovery_action="failed_terminal",
                        extra={"reason": "rollback_exhausted_or_missing_checkpoint"},
                    )
                )
                state.status = "FAILED"
                await self.memory.save_workflow_state(state)
                logger.error(
                    _wfe_t(
                        "wfe.err.phase_fatal",
                        wid=state.workflow_id,
                        nid=node_id,
                    ),
                )
                get_experience_sink().end_episode(
                    state.workflow_id,
                    "failed",
                    pop_context=False,
                    extra_meta={"node_id": node_id, "error": err_s, "failure_class": "phase_fatal"},
                )
                self._try_complete_workflow_future(
                    state,
                    RuntimeError(_wfe_t("wfe.error.node_failed", node_id=node_id, detail=err_s)),
                )
                if hasattr(self, "reflexion_loop") and self.reflexion_loop:
                    await self.reflexion_loop.trigger_reflexion(
                        workflow_id=state.workflow_id,
                        chat_id=state.chat_id,
                        failure_context={
                            "node_id": node_id,
                            "error": err_s,
                            "task_description": state.context.get("original_task", "unknown task"),
                        },
                    )
                return

            retries = state.error_retry_counts.get(node_id, 0) + 1
            state.error_retry_counts[node_id] = retries

            if retries <= node.max_retries:
                state.history.append(
                    failure_audit_record(
                        node_id=node_id,
                        error=err_s,
                        failure_class="transient",
                        retries_at_failure=retries,
                        recovery_action="retry_scheduled",
                    )
                )
                logger.warning(
                    _wfe_t(
                        "wfe.warn.transient_retry",
                        nid=node_id,
                        cur=retries,
                        mx=node.max_retries,
                    ),
                )
                await self.memory.save_workflow_state(state)
                asyncio.create_task(self._execute_node(state))
            else:
                state.history.append(
                    failure_audit_record(
                        node_id=node_id,
                        error=err_s,
                        failure_class="transient",
                        retries_at_failure=retries,
                        recovery_action="failed_terminal",
                    )
                )
                state.status = "FAILED"
                await self.memory.save_workflow_state(state)
                logger.error(
                    _wfe_t(
                        "wfe.err.wf_fail",
                        wid=state.workflow_id,
                        nid=node_id,
                    )
                )
                get_experience_sink().end_episode(
                    state.workflow_id,
                    "failed",
                    pop_context=False,
                    extra_meta={"node_id": node_id, "error": err_s, "failure_class": "transient"},
                )
                self._try_complete_workflow_future(
                    state,
                    RuntimeError(_wfe_t("wfe.error.node_failed", node_id=node_id, detail=err_s)),
                )

                if hasattr(self, "reflexion_loop") and self.reflexion_loop:
                    await self.reflexion_loop.trigger_reflexion(
                        workflow_id=state.workflow_id,
                        chat_id=state.chat_id,
                        failure_context={
                            "node_id": node_id,
                            "error": err_s,
                            "task_description": state.context.get("original_task", "unknown task"),
                        },
                    )
        finally:
            if multi_tenant_guard:
                multi_tenant_guard.release_lock(lock_key, state.chat_id)  # 移除 await

    # ====================== 【ReflexionLoop 自愈接口】 ======================
    async def retry_node(self, workflow_id: str, node_id: str, chat_id: str) -> bool:
        """重置指定节点的重试计数并重新执行（带锁保护）"""
        lock_key = f"wf_{workflow_id}"
        if multi_tenant_guard:
            await multi_tenant_guard.acquire_lock(lock_key, chat_id)
        try:
            state = await self.memory.get_workflow_state(workflow_id, chat_id)
            if not state or state.status != "FAILED":
                return False
            state.error_retry_counts[node_id] = 0
            state.current_node_id = node_id
            state.status = "RUNNING"
            await self.memory.save_workflow_state(state)
            asyncio.create_task(self._execute_node(state))
            logger.debug(_wfe_t("wfe.debug.self_heal_retry", nid=node_id, wid=workflow_id))
            return True
        finally:
            if multi_tenant_guard:
                multi_tenant_guard.release_lock(lock_key, chat_id)  # 移除 await

    async def modify_node_config(
        self, workflow_id: str, node_id: str, new_config: Dict[str, Any], chat_id: str
    ) -> bool:
        """【核心强化】修改节点配置并重置重试计数（支持 ReflexionLoop 动态 new_config）"""
        lock_key = f"wf_{workflow_id}"
        if multi_tenant_guard:
            await multi_tenant_guard.acquire_lock(lock_key, chat_id)
        try:
            state = await self.memory.get_workflow_state(workflow_id, chat_id)
            if not state or node_id not in state.nodes:
                logger.warning(_wfe_t("wfe.warn.modify_fail", wid=workflow_id, nid=node_id))
                return False

            # ====================== 【本次核心强化】实际配置更新 + observability ======================
            async with observability.start_span(
                span_name="workflow.node.modify_config",
                workflow_id=workflow_id,
                node_id=node_id,
                chat_id=chat_id,
                attributes={"new_config": str(new_config)},
            ):
                old_config = dict(state.nodes[node_id].config)  # 备份旧配置
                state.nodes[node_id].config.update(new_config)

                state.error_retry_counts[node_id] = 0
                state.status = "RUNNING"

                await self.memory.save_workflow_state(state)
                asyncio.create_task(self._execute_node(state))

                logger.debug(
                    _wfe_t(
                        "wfe.debug.modify_ok",
                        nid=node_id,
                        wid=workflow_id,
                        old=old_config,
                        new=state.nodes[node_id].config,
                    )
                )
                return True
        finally:
            if multi_tenant_guard:
                multi_tenant_guard.release_lock(lock_key, chat_id)  # 移除 await

    async def skip_node(self, workflow_id: str, node_id: str, chat_id: str) -> bool:
        """跳过失败节点，直接路由到下一个节点（带锁保护）"""
        lock_key = f"wf_{workflow_id}"
        if multi_tenant_guard:
            await multi_tenant_guard.acquire_lock(lock_key, chat_id)
        try:
            state = await self.memory.get_workflow_state(workflow_id, chat_id)
            if not state:
                return False
            next_nodes = state.edges.get(node_id, [])
            if not next_nodes:
                return False
            next_node_id = next_nodes[0]
            state.current_node_id = next_node_id
            state.status = "RUNNING"
            await self.memory.save_workflow_state(state)
            asyncio.create_task(self._execute_node(state))
            logger.debug(_wfe_t("wfe.debug.skip_node", nid=node_id, nxt=next_node_id))
            return True
        finally:
            if multi_tenant_guard:
                multi_tenant_guard.release_lock(lock_key, chat_id)  # 移除 await

    # ====================== 控制方法 ======================
    async def pause_workflow(self, workflow_id: str):
        state = await self.memory.get_workflow_state_by_workflow_id(workflow_id)
        if not state:
            return
        lock_key = f"wf_{workflow_id}"
        if multi_tenant_guard:
            await multi_tenant_guard.acquire_lock(lock_key, state.chat_id)
        try:
            state.status = "PAUSED"
            await self.memory.save_workflow_state(state)
            logger.debug(_wfe_t("wfe.debug.paused", wid=workflow_id))
        finally:
            if multi_tenant_guard:
                multi_tenant_guard.release_lock(lock_key, state.chat_id)  # 移除 await

    async def cancel_workflow(self, workflow_id: str):
        """HITL「取消任务」：标记 CANCELLED 并收口 Future（与 hitl_handler 对齐）。"""
        state = await self.memory.get_workflow_state_by_workflow_id(workflow_id)
        if not state:
            return
        lock_key = f"wf_{workflow_id}"
        if multi_tenant_guard:
            await multi_tenant_guard.acquire_lock(lock_key, state.chat_id)
        try:
            state.status = "CANCELLED"
            await self.memory.save_workflow_state(state)
            get_experience_sink().end_episode(state.workflow_id, "cancelled", pop_context=False)
            self._try_complete_workflow_future(
                state, RuntimeError(_wfe_t("wfe.error.workflow_cancelled", workflow_id=workflow_id))
            )
            logger.info(_wfe_t("wfe.log.cancelled", wid=workflow_id))
        finally:
            if multi_tenant_guard:
                multi_tenant_guard.release_lock(lock_key, state.chat_id)

    async def resume_workflow(self, workflow_id: str, user_input: Optional[Dict] = None):
        """HITL RESUME 入口（带锁保护）"""
        state = await self.memory.get_workflow_state_by_workflow_id(workflow_id)
        if not state or state.status != "PAUSED":
            return
        lock_key = f"wf_{workflow_id}"
        if multi_tenant_guard:
            await multi_tenant_guard.acquire_lock(lock_key, state.chat_id)
        try:
            state.status = "RUNNING"
            ui = dict(user_input) if user_input else {}
            mode = ui.pop("resume_mode", "continue")
            replay_phase = ui.pop("replay_phase", None)
            if mode == "replay_from_phase" and replay_phase:
                await apply_replay_from_phase_checkpoint(state, self.memory, str(replay_phase))
            if ui:
                state.context.update(ui)
            await checkpoint_hitl_boundary(
                state,
                self.memory,
                self.bus,
                kind="post_hitl_resume",
                node_id=state.current_node_id,
                reason="hitl_resume",
                source_module="workflow.engine",
            )
            await self.memory.save_workflow_state(state)
            asyncio.create_task(self._execute_node(state))
            logger.debug(_wfe_t("wfe.debug.resumed", wid=workflow_id))
        finally:
            if multi_tenant_guard:
                multi_tenant_guard.release_lock(lock_key, state.chat_id)  # 移除 await

    async def _is_high_risk_action(self, node: Node) -> bool:
        """高危动作检测（用于触发 HITL）"""
        if node.node_type == "TOOL" and any(
            k in str(node.config).lower() for k in ["delete", "remove", "rm", "send_email"]
        ):
            return True
        return False

    async def shutdown(self):
        if self._subscription_task and not self._subscription_task.done():
            self._subscription_task.cancel()
        logger.debug(_wfe_t("wfe.debug.shutdown"))


# --- END OF FILE workflow_engine.py ---
