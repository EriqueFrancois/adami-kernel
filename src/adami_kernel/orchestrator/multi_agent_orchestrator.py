# src/adami_kernel/orchestrator/multi_agent_orchestrator.py
import asyncio
import logging
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from adami_kernel.config import settings
from adami_kernel.cortex.meta_cortex import MetaCortex
from adami_kernel.cortex.tools_manager import ToolboxManager
from adami_kernel.guardian.immunity import ImmunitySystem
from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.i18n import t
from adami_kernel.i18n.ui_static import catalog_pipe_tokens, task_matches_pipe_catalog
from adami_kernel.nexus.bus import EventBus
from adami_kernel.nexus.event import AdamiEvent, EventPriority
from adami_kernel.orchestrator import planner_prompts as _pp
from adami_kernel.orchestrator.agent_models import AgentMessage, AgentRole, AgentTask
from adami_kernel.orchestrator.agents.executor import ExecutorAgent
from adami_kernel.orchestrator.hitl_handler import hitl_handler
from adami_kernel.orchestrator.long_task_phase_gate import (
    LongTaskPhase,
    checkpoint_hitl_boundary,
    emit_phase_transition_if_changed,
    long_task_phase_for_agent_role,
)
from adami_kernel.orchestrator.multi_tenant_guard import multi_tenant_guard
from adami_kernel.orchestrator.workflow_models import Node, WorkflowState, ensure_default_profile_id
from adami_kernel.telemetry.experience_sink import (
    experience_episode_id_ctx,
    experience_primary_trace_ctx,
    get_experience_sink,
    infer_tool_audit_meta,
    redact_payload,
    summarize_text,
)

logger = logging.getLogger("AdamI-MultiAgentOrchestrator")


def _orch_ui_t(key: str, **kwargs: Any) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


def _agent_role_label(role: Any) -> str:
    if hasattr(role, "value"):
        return str(role.value)
    return str(role)


class MultiAgentOrchestrator(MetaCortex):
    """
    AdamI 多代理编排器（Phase 3 + 增强后备）
    【BugFix】修复 JSON 序列化时的 Circular Reference (循环引用) 问题。
    【本次修复】：删除本地 _is_skill_creation_task，统一依赖 SkillRouter 单点检测（全局意图零重复）
    【本次增强】：Executor 参数优先使用 SkillRouter 返回的 _executor_args，确保城市名等参数正确传递。
    【本次核心安全修复】：CONDITION 节点彻底移除 eval()，改用正则 + safe_get 安全求值
    【本次最终修复】：hitl_handler None 防护 + 安全降级，彻底解决 'NoneType' object has no attribute 'trigger_paused'
    【本次阶段2 优化】：Engineer 微重试专用 300 秒超时 + 重试循环缩短至 2 次，解决微重试被外层打断问题
    【Step 3 新增】：结果缓存与中间态检查点（Checkpointing）机制 - Researcher 成功后强制保存 checkpoint，后续重试直接读取缓存
    【本次诊断强化】_handle_agent_message 增加详细消息收发日志，帮助定位 Researcher 消息丢失问题。
    【本次修复】：Orchestrator 超时竞态条件保护，防止 Engineer 等快速完成任务被误判超时重试（future.done() + key 检查）。
    【本次修复】：增强 _handle_agent_message 异常日志 + 发布事件确认日志 + 超时后 future.done() 完整检查，彻底解决 Engineer 消息丢失导致的无限重试问题。
    【本次最终修复】：完善 _orchestrate 的 TimeoutError 处理，在 future 已不存在时检查 state.context 是否已有结果，彻底消除 Engineer 成功注册后“消息未到达”的逻辑幻觉死循环。
    【本次修复】：_handle_agent_message 中当 target_agent == ORCHESTRATOR 且 future 已不存在时立即 return，彻底阻止 Engineer 消息被重复处理。
    """

    def __init__(self, bus: EventBus, memory: LayeredMemory, toolbox: ToolboxManager):
        super().__init__(router=None, memory=memory, evolution_engine=None, curiosity_queue=None)
        self.bus = bus
        self.memory = memory
        self.toolbox = toolbox
        self.evolution_engine = None
        self.router = None
        self.skill_router = None
        self.immunity = ImmunitySystem()

        self.active_orchestrations: Dict[str, WorkflowState] = {}
        self.agents: Dict[AgentRole, Any] = {}
        self.task_futures: Dict[str, asyncio.Future] = {}
        self.workflow_futures: Dict[str, asyncio.Future] = {}
        self._subscription_task: Optional[asyncio.Task] = None

        self._error_fingerprints: Dict[str, Dict[str, int]] = {}

        logger.info("[MultiAgentOrchestrator] ready")

    async def _hitl_pre_pause_phase(self, state: WorkflowState, reason: str) -> None:
        await checkpoint_hitl_boundary(
            state,
            self.memory,
            self.bus,
            kind="pre_hitl_pause",
            reason=reason,
            source_module="multi_agent_orchestrator",
        )

    async def _save_researcher_checkpoint(
        self,
        workflow_id: str,
        researcher_result: Dict[str, Any],
        workflow_state_version: Optional[int] = None,
    ) -> None:
        """【Step 3 新增】Researcher 成功后强制保存 checkpoint（双保险）；步骤 2 写入 workflow_state_version。"""
        try:
            if not isinstance(researcher_result, dict) or "summary" not in researcher_result:
                return
            checkpoint_data = {
                "summary": researcher_result["summary"],
                "sources": researcher_result.get("sources", []),
                "timestamp": asyncio.get_event_loop().time(),
                "status": "success",
                "original_task": researcher_result.get("original_task", ""),
            }
            await self.memory.save_workflow_phase_checkpoint(
                workflow_id,
                "researcher",
                checkpoint_data,
                workflow_state_version=workflow_state_version,
                expected_seq=None,
                update_last_good=True,
            )
            logger.info(_orch_ui_t("orch.magent.log.checkpoint_saved", wid=workflow_id))
        except Exception as e:
            logger.warning(_orch_ui_t("orch.magent.warn.checkpoint_fail", e=e))

    def _record_workflow_error(self, workflow_id: str, error: Exception) -> bool:
        fingerprint = f"{type(error).__name__}:{str(error)[:100]}"
        if workflow_id not in self._error_fingerprints:
            self._error_fingerprints[workflow_id] = {}
        counts = self._error_fingerprints[workflow_id]
        counts[fingerprint] = counts.get(fingerprint, 0) + 1
        count = counts[fingerprint]

        logger.warning(
            _orch_ui_t(
                "orch.magent.warn.circuit_fingerprint",
                wid=workflow_id,
                fp=fingerprint,
                count=count,
            )
        )
        return count >= 3

    def set_evolution_engine(self, evolution_engine):
        self.evolution_engine = evolution_engine
        self.executor_agent = ExecutorAgent(evolution_engine, self.memory)
        logger.debug("[MultiAgentOrchestrator] evolution_engine set, ExecutorAgent created")

    def set_router(self, router):
        self.router = router
        logger.debug("[MultiAgentOrchestrator] router set")

    def set_skill_router(self, skill_router):
        self.skill_router = skill_router
        logger.debug("[MultiAgentOrchestrator] skill_router set")

    async def initialize(self):
        self._subscription_task = asyncio.create_task(self._listen_agent_messages())
        logger.debug("[MultiAgentOrchestrator] subscribed agent.communication")

    async def _listen_agent_messages(self):
        q = await self.bus.subscribe("agent.communication")
        while True:
            try:
                event: AdamiEvent = await asyncio.wait_for(
                    q.get(), timeout=float(settings.ADAMI_ORCHESTRATOR_QUEUE_POLL_SEC)
                )
                if event.target_topic == "agent.communication":
                    await self._handle_agent_message(event)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(_orch_ui_t("orch.magent.err.listen", e=e), exc_info=True)

    async def _handle_agent_message(self, event: AdamiEvent):
        try:
            msg = AgentMessage.model_validate(event.payload)

            # ====================== 【本次诊断强化】收到消息诊断日志 ======================
            logger.info(
                _orch_ui_t(
                    "orch.magent.log.recv",
                    src=msg.source_agent,
                    tgt=msg.target_agent,
                    wid=msg.workflow_id,
                    mtype=msg.message_type,
                )
            )
            # =================================================================================

            logger.debug(
                _orch_ui_t(
                    "orch.magent.debug.recv_short",
                    src=msg.source_agent,
                    tgt=msg.target_agent,
                    mtype=msg.message_type,
                    wid=msg.workflow_id,
                )
            )

            if msg.target_agent == AgentRole.ORCHESTRATOR:
                key = f"{msg.workflow_id}_{msg.source_agent}"

                # ====================== 【本次诊断强化】future 查找诊断日志 ======================
                logger.info(
                    _orch_ui_t(
                        "orch.magent.log.future_lookup",
                        fkey=key,
                        exists=key in self.task_futures,
                    )
                )
                # =================================================================================

                future = self.task_futures.pop(key, None)
                if future:
                    if msg.message_type == "result":
                        future.set_result(msg.payload.get("result", {}))
                    elif msg.message_type == "feedback":
                        future.set_result(msg.payload)
                    else:
                        future.set_exception(Exception(msg.payload.get("error", "Unknown error")))
                    logger.info(_orch_ui_t("orch.magent.log.future_set", fkey=key))
                else:
                    logger.debug(_orch_ui_t("orch.magent.debug.future_missing", fkey=key))
                    return  # ← 关键：直接返回，防止 Engineer 消息被重复处理
                return

            if msg.target_agent in self.agents:
                result_msg = await self.agents[msg.target_agent].process(msg)
                if result_msg:
                    result_event = AdamiEvent(
                        trace_id=result_msg.trace_id,
                        source_module="multi_agent_orchestrator",
                        target_topic="agent.communication",
                        priority=EventPriority.NORMAL,
                        payload=result_msg.to_event_payload(),
                    )
                    await self.bus.publish(result_event)
                    # ====================== 【本次修复】发布事件确认日志 ======================
                    logger.info(
                        _orch_ui_t(
                            "orch.magent.log.event_published",
                            src=result_msg.source_agent,
                            tgt=result_msg.target_agent,
                            tid=result_msg.trace_id,
                        )
                    )
                    # =================================================================================
            else:
                logger.warning(
                    _orch_ui_t(
                        "orch.magent.warn.agent_missing",
                        tgt=msg.target_agent,
                        keys=list(self.agents.keys()),
                    )
                )
        except Exception as e:
            logger.error(_orch_ui_t("orch.magent.err.handle_msg", e=e), exc_info=True)

    async def execute_workflow(self, chat_id: str, workflow_state: WorkflowState) -> asyncio.Future:
        if multi_tenant_guard:
            await multi_tenant_guard.validate_chat_id(chat_id)

        workflow_state.chat_id = chat_id
        workflow_state.status = "RUNNING"
        await self.memory.save_workflow_state(workflow_state)
        self.active_orchestrations[workflow_state.workflow_id] = workflow_state

        get_experience_sink().begin_episode(
            workflow_state.workflow_id,
            workflow_state.workflow_id,
            push_context=False,
            source="multi_agent.execute_workflow",
            chat_id=str(chat_id),
        )

        future = asyncio.get_event_loop().create_future()
        self.workflow_futures[workflow_state.workflow_id] = future

        asyncio.create_task(self._execute_workflow(workflow_state))
        logger.info(_orch_ui_t("orch.magent.log.generic_workflow", wid=workflow_state.workflow_id))
        return future

    async def _execute_workflow(self, state: WorkflowState):
        tok_e = experience_episode_id_ctx.set(state.workflow_id)
        tok_p = experience_primary_trace_ctx.set(state.workflow_id)
        future = self.workflow_futures.get(state.workflow_id)
        try:
            start_node = state.current_node_id or self._find_start_node(state)
            if not start_node:
                raise ValueError(_orch_ui_t("orch.magent.error.no_start_node"))
            state.current_node_id = start_node
            await self.memory.save_workflow_state(state)

            while state.status == "RUNNING":
                node = state.nodes.get(state.current_node_id)
                if not node:
                    logger.error(
                        _orch_ui_t("orch.magent.err.node_missing", nid=state.current_node_id)
                    )
                    state.status = "FAILED"
                    break

                await self._execute_node(state, node)

                next_nodes = state.edges.get(node.node_id, [])
                if not next_nodes:
                    state.status = "SUCCESS"
                    break
                state.current_node_id = next_nodes[0]
                await self.memory.save_workflow_state(state)

            if future and not future.done():
                if state.status == "SUCCESS":
                    final_result = state.context
                    future.set_result(final_result)
                else:
                    future.set_exception(
                        Exception(
                            _orch_ui_t("orch.magent.error.workflow_ended", status=state.status)
                        )
                    )

        except Exception as e:
            logger.error(_orch_ui_t("orch.magent.err.workflow_exec", e=e), exc_info=True)
            state.status = "FAILED"
            await self.memory.save_workflow_state(state)
            if future and not future.done():
                future.set_exception(e)
        finally:
            experience_episode_id_ctx.reset(tok_e)
            experience_primary_trace_ctx.reset(tok_p)
            sink = get_experience_sink()
            st = state.status
            if st == "SUCCESS":
                sink.end_episode(state.workflow_id, "success", pop_context=False)
            elif st == "FAILED":
                sink.end_episode(state.workflow_id, "failed", pop_context=False)
            self.workflow_futures.pop(state.workflow_id, None)

    async def _execute_node(self, state: WorkflowState, node: Node):
        logger.debug(
            _orch_ui_t("orch.magent.debug.run_node", nid=node.node_id, ntype=node.node_type)
        )
        try:
            if node.node_type == "SKILL_CALL":
                skill_name = node.config.get("skill_name")
                args = self._resolve_args(node.config.get("args", {}), state.context)
                if not self.evolution_engine:
                    raise Exception(_orch_ui_t("orch.magent.error.evolution_engine_missing"))
                skill_func = self.evolution_engine.get_skill(skill_name)
                if not skill_func:
                    raise Exception(
                        _orch_ui_t("orch.magent.error.skill_not_found", skill_name=skill_name)
                    )
                t0 = time.perf_counter()
                result = await skill_func(**args)
                latency_ms = (time.perf_counter() - t0) * 1000
                meta = infer_tool_audit_meta(self.evolution_engine, str(skill_name))
                get_experience_sink().record_tool_call(
                    trace_id=f"magent_{state.workflow_id}_{node.node_id}",
                    episode_id=state.workflow_id,
                    tool_name=str(skill_name),
                    tool_id=meta["tool_id"],
                    args_summary=summarize_text(str(redact_payload(args))[:2000]),
                    result_summary=summarize_text(str(redact_payload(result))[:2000]),
                    ok=True,
                    tool_backend=meta["tool_backend"],
                    latency_ms=latency_ms,
                    docker_used=meta["docker_used"],
                    mcp_allow_deny=meta["mcp_allow_deny"],
                    extra={"node_id": node.node_id, "path": "multi_agent_orchestrator.SKILL_CALL"},
                )

                if isinstance(result, dict):
                    safe_dict = dict(result)
                    state.context[node.node_id] = safe_dict
                    state.context[node.node_id]["result"] = dict(result)
                else:
                    state.context[node.node_id] = {"result": result, "status": "success"}

            elif node.node_type == "LLM_CALL":
                if not self.router:
                    raise Exception(_orch_ui_t("orch.magent.error.router_missing"))
                prompt_template = node.config.get("prompt", "")
                prompt = self._resolve_string(prompt_template, state.context)
                response = await self.router.call_llm(
                    prompt, brain_type=node.config.get("brain_type", "think")
                )
                state.context[node.node_id] = {"response": response}

            elif node.node_type == "CONDITION":
                condition_template = node.config.get("condition", "")

                def safe_get(path):
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
                            _orch_ui_t(
                                "orch.magent.error.invalid_condition",
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

                    result = False
                    if operator == "==":
                        result = str(left_val) == str(right_val)
                    elif operator == "!=":
                        result = str(left_val) != str(right_val)
                    elif operator == ">":
                        result = (
                            (float(left_val) > float(right_val)) if left_val is not None else False
                        )
                    elif operator == ">=":
                        result = (
                            (float(left_val) >= float(right_val)) if left_val is not None else False
                        )
                    elif operator == "<":
                        result = (
                            (float(left_val) < float(right_val)) if left_val is not None else False
                        )
                    elif operator == "<=":
                        result = (
                            (float(left_val) <= float(right_val)) if left_val is not None else False
                        )

                    logger.info(
                        _orch_ui_t(
                            "orch.magent.log.cond_ok",
                            path=var_path,
                            left=left_val,
                            op=operator,
                            right=right_val,
                            result=result,
                        )
                    )
                except Exception as e:
                    logger.error(
                        _orch_ui_t(
                            "orch.magent.err.cond_eval",
                            tpl=condition_template,
                            e=e,
                        )
                    )
                    result = False

                true_next = node.config.get("true_next")
                false_next = node.config.get("false_next")

                if result and true_next:
                    state.edges[node.node_id] = [true_next]
                elif not result and false_next:
                    state.edges[node.node_id] = [false_next]
                else:
                    next_nodes = state.edges.get(node.node_id, [])
                    if next_nodes:
                        default_target = next_nodes[0]
                        logger.warning(
                            _orch_ui_t(
                                "orch.magent.warn.cond_fallback",
                                target=default_target,
                            )
                        )
                        state.edges[node.node_id] = [default_target]
                    else:
                        raise Exception(_orch_ui_t("orch.magent.error.condition_branch"))

                state.context[node.node_id] = {"condition_result": result}

            else:
                raise NotImplementedError(
                    _orch_ui_t("orch.magent.error.unsupported_node", node_type=node.node_type)
                )

            state.history.append(
                {
                    "node_id": node.node_id,
                    "status": "SUCCESS",
                    "result": state.context.get(node.node_id),
                    "timestamp": asyncio.get_event_loop().time(),
                }
            )
            await self.memory.save_workflow_state(state)

        except Exception as e:
            logger.error(_orch_ui_t("orch.magent.err.node_exec", nid=node.node_id, e=e))
            if node.node_type == "SKILL_CALL":
                sn = str(node.config.get("skill_name") or "unknown")
                meta = infer_tool_audit_meta(self.evolution_engine, sn)
                get_experience_sink().record_tool_call(
                    trace_id=f"magent_{state.workflow_id}_{node.node_id}",
                    episode_id=state.workflow_id,
                    tool_name=sn,
                    tool_id=meta["tool_id"],
                    args_summary=summarize_text(
                        str(redact_payload(node.config.get("args", {})))[:2000]
                    ),
                    result_summary="",
                    ok=False,
                    error_code=type(e).__name__,
                    tool_backend=meta["tool_backend"],
                    docker_used=meta["docker_used"],
                    mcp_allow_deny=meta["mcp_allow_deny"],
                    extra={"node_id": node.node_id, "path": "multi_agent_orchestrator.SKILL_CALL"},
                )
            state.history.append(
                {
                    "node_id": node.node_id,
                    "status": "FAILED",
                    "error": str(e),
                    "timestamp": asyncio.get_event_loop().time(),
                }
            )
            await self.memory.save_workflow_state(state)
            raise

    def _resolve_args(self, args_spec: Dict, context: Dict) -> Dict:
        result = {}
        for k, v in args_spec.items():
            if isinstance(v, str) and v.startswith("$context."):
                path = v[9:]
                parts = path.split(".")
                value = context
                for part in parts:
                    if isinstance(value, dict):
                        value = value.get(part)
                    else:
                        value = None
                        break
                result[k] = value
            elif isinstance(v, dict):
                result[k] = self._resolve_args(v, context)
            else:
                result[k] = v
        return result

    def _resolve_string(self, template: str, context: Dict) -> str:
        def replacer(match):
            path = match.group(1)
            parts = path.split(".")
            value = context
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    value = None
                    break
            return str(value) if value is not None else ""

        return re.sub(r"\$context\.([a-zA-Z0-9_.]+)", replacer, template)

    def _find_start_node(self, state: WorkflowState) -> Optional[str]:
        for node_id in state.nodes:
            return node_id
        return None

    async def start_multi_agent_workflow(
        self, chat_id: str, task_description: str, initial_context: Optional[Dict[str, Any]] = None
    ) -> asyncio.Future:
        if multi_tenant_guard:
            await multi_tenant_guard.validate_chat_id(chat_id)

        logger.info(_orch_ui_t("orch.magent.log.start_multi"))
        try:
            state = WorkflowState(
                chat_id=chat_id,
                status="RUNNING",
                current_node_id="__orchestrator_start__",
                nodes={
                    "__orchestrator_start__": Node(
                        node_id="__orchestrator_start__",
                        node_type="START",
                        config={"prompt": task_description},
                    )
                },
                edges={"__orchestrator_start__": ["research"]},
                context={"original_task": task_description},
                history=[],
                global_step_count=0,
                max_steps=50,
            )
            if initial_context:
                state.context.update(initial_context)

            if initial_context and "original_user_task" in initial_context:
                state.context["original_user_task"] = initial_context["original_user_task"]
            else:
                state.context["original_user_task"] = task_description

            # Orchestration-only metadata for logs / filtering (not Report Studio or SecondBrain).
            ensure_default_profile_id(state, "multi_agent_orchestrator")

            await self.memory.save_workflow_state(state)
            self.active_orchestrations[state.workflow_id] = state

            get_experience_sink().begin_episode(
                state.workflow_id,
                state.workflow_id,
                push_context=False,
                source="multi_agent.start_multi_agent_workflow",
                chat_id=str(chat_id),
            )

            future = asyncio.get_event_loop().create_future()
            self.workflow_futures[state.workflow_id] = future

            asyncio.create_task(self._orchestrate(state))

            logger.info(_orch_ui_t("orch.magent.log.started", wid=state.workflow_id))
            return future
        except Exception as e:
            logger.error(_orch_ui_t("orch.magent.err.start_fail", e=e))
            future = asyncio.get_event_loop().create_future()
            future.set_exception(e)
            return future

    async def _lookup_skill(
        self, task_description: str, chat_id: str
    ) -> Optional[Tuple[str, Dict]]:
        """技能查找（已完全依赖 SkillRouter 单点检测）"""
        if not self.skill_router:
            return None

        try:
            if not task_description:
                return None
            spec = await self.skill_router.get_call_spec(task_description)
            if not spec:
                logger.info(_orch_ui_t("orch.magent.log.skillrouter_none"))
                return None

            skill_name, args = spec

            if self.evolution_engine and not self.evolution_engine.get_skill(skill_name):
                logger.warning(_orch_ui_t("orch.magent.warn.skillrouter_stale", name=skill_name))
                return None

            logger.info(_orch_ui_t("orch.magent.log.skill_lookup_ok", name=skill_name, args=args))
            return (skill_name, args)
        except Exception as e:
            logger.error(_orch_ui_t("orch.magent.err.skill_lookup", e=e))
            return None

    async def _generate_dag(self, task_description: str) -> List[AgentTask]:
        return [
            AgentTask(
                agent_role=AgentRole.RESEARCHER,
                description=task_description,
                required_output_schema={"summary": "string", "sources": "array"},
                context_keys=["original_task"],
            ),
            AgentTask(
                agent_role=AgentRole.ENGINEER,
                description=_pp.MULTI_AGENT_ENGINEER_DESCRIPTION,
                required_output_schema={"code": "string", "skill_name": "string"},
                context_keys=["researcher"],
            ),
            AgentTask(
                agent_role=AgentRole.EXECUTOR,
                description=_pp.MULTI_AGENT_EXECUTOR_DESCRIPTION,
                required_output_schema={"execution_result": "any"},
                context_keys=["engineer"],
            ),
            AgentTask(
                agent_role=AgentRole.CRITIC,
                description=_pp.MULTI_AGENT_CRITIC_DESCRIPTION,
                required_output_schema={"approved": "boolean", "feedback": "string"},
                context_keys=["engineer", "executor"],
            ),
        ]

    async def _distribute_and_wait(self, task_dict: Dict[str, Any], state: WorkflowState):
        task = AgentTask.model_validate(task_dict)
        key = f"{state.workflow_id}_{task.agent_role}"
        future = asyncio.get_event_loop().create_future()
        self.task_futures[key] = future
        logger.debug(_orch_ui_t("orch.magent.debug.future_create", fkey=key))

        payload = {"task": task.model_dump()}
        if task.agent_role == AgentRole.ENGINEER:
            researcher_result = state.context.get("researcher", {})
            if researcher_result is None:
                researcher_result = {}
            researcher_result["original_task"] = state.context.get("original_task", "")
            payload["result"] = researcher_result
            ot = str(researcher_result.get("original_task", ""))[:80]
            logger.debug(_orch_ui_t("orch.magent.debug.engineer_ctx", snippet=ot))
        elif task.agent_role == AgentRole.EXECUTOR:
            skill_name = state.context.get("_skill_name")
            if not skill_name:
                engineer_result = state.context.get("engineer", {})
                extracted_skill_name = (
                    engineer_result.get("skill_name") if isinstance(engineer_result, dict) else None
                )
                if extracted_skill_name:
                    skill_name = extracted_skill_name

            if skill_name:
                executor_args = state.context.get("_executor_args", {})
                if not executor_args and state.context.get("_is_creation_flow"):
                    original_task = state.context.get("original_task", "")
                    if task_matches_pipe_catalog(original_task, "dp.intent.pipe_weather"):
                        executor_args = {"city": _orch_ui_t("eng.fixtures.weather_test_city")}
                    elif (
                        task_matches_pipe_catalog(original_task, "planner.pipe.crypto_param_hints")
                        or "crypto" in original_task.lower()
                    ):
                        executor_args = {"coin": "bitcoin"}
                elif not executor_args:
                    original_task = state.context.get("original_task", "")
                    city = self._extract_city(original_task)
                    executor_args = {"city": city} if city else {}
                payload["skill_name"] = skill_name
                payload["args"] = executor_args
                logger.info(
                    _orch_ui_t(
                        "orch.magent.log.executor_payload",
                        name=skill_name,
                        args=executor_args,
                    )
                )
            else:
                engineer_result = state.context.get("engineer", {})
                payload["result"] = engineer_result
                payload["original_task"] = state.context.get("original_task", "")
                payload["context"] = state.context
        elif task.context_keys:
            context_results = {k: state.context.get(k) for k in task.context_keys}
            if any(v is not None for v in context_results.values()):
                payload["result"] = context_results
                logger.debug(
                    _orch_ui_t(
                        "orch.magent.debug.role_ctx",
                        role=_agent_role_label(task.agent_role),
                        keys=list(context_results.keys()),
                    )
                )

        msg = AgentMessage(
            source_agent=AgentRole.ORCHESTRATOR,
            target_agent=task.agent_role,
            message_type="task",
            payload=payload,
            workflow_id=state.workflow_id,
            chat_id=state.chat_id,
        )
        event = AdamiEvent(
            trace_id=f"orchestrator_{uuid.uuid4().hex[:8]}",
            source_module="multi_agent_orchestrator",
            target_topic="agent.communication",
            priority=EventPriority.NORMAL,
            payload=msg.to_event_payload(),
        )
        await self.bus.publish(event)
        logger.info(
            _orch_ui_t("orch.magent.log.task_sent", role=_agent_role_label(task.agent_role))
        )

        try:
            result = await future
            return result
        except Exception as e:
            if task_matches_pipe_catalog(str(e), "orch.pipe.skill_missing_tokens"):
                logger.warning(_orch_ui_t("orch.magent.warn.executor_missing_skill"))
                return {"status": "error", "error": str(e)}
            raise
        finally:
            self.task_futures.pop(key, None)
            logger.debug(_orch_ui_t("orch.magent.debug.future_clear", fkey=key))

    def _extract_city(self, text: str) -> Optional[str]:
        common_cities = list(catalog_pipe_tokens("shared.pipe.common_cities_cn"))[:19]
        for city in common_cities:
            if city in text:
                return city
        match = re.search(r"([\u4e00-\u9fff]{2,4})", text)
        if match:
            return match.group(1)
        return None

    async def _orchestrate(self, state: WorkflowState):
        tok_e = experience_episode_id_ctx.set(state.workflow_id)
        tok_p = experience_primary_trace_ctx.set(state.workflow_id)
        future = self.workflow_futures.get(state.workflow_id)
        try:
            while state.status == "RUNNING":
                current_task = state.context.get("current_task")
                if not current_task:
                    original_task = state.context.get("original_task", "")
                    skill_lookup_result = await self._lookup_skill(original_task, state.chat_id)
                    if skill_lookup_result:
                        skill_name, args = skill_lookup_result
                        executor_task = AgentTask(
                            agent_role=AgentRole.EXECUTOR,
                            description=_pp.MULTI_AGENT_EXECUTOR_EXISTING.format(
                                skill_name=skill_name
                            ),
                            required_output_schema={"execution_result": "any"},
                            context_keys=[],
                        )
                        critic_task = AgentTask(
                            agent_role=AgentRole.CRITIC,
                            description=_pp.MULTI_AGENT_CRITIC_REVIEW_EXECUTION,
                            required_output_schema={"approved": "boolean", "feedback": "string"},
                            context_keys=["executor"],
                        )
                        dag = [executor_task, critic_task]
                        state.context["_skill_name"] = skill_name
                        state.context["_executor_args"] = args
                        dag_dict = [task.model_dump() for task in dag]
                        state.context["dag"] = dag_dict
                        state.context["current_task"] = dag_dict[0]
                        await self.memory.save_workflow_state(state)
                        current_task = dag_dict[0]
                        logger.info(_orch_ui_t("orch.magent.log.skill_fastpath", name=skill_name))
                    else:
                        dag = await self._generate_dag(state.context["original_task"])
                        dag_dict = [task.model_dump() for task in dag]
                        state.context["dag"] = dag_dict
                        state.context["_is_creation_flow"] = True
                        state.context["current_task"] = dag_dict[0]
                        await self.memory.save_workflow_state(state)
                        current_task = dag_dict[0]
                        logger.info(_orch_ui_t("orch.magent.log.full_pipeline"))

                # 【阶段2 优化】ENGINEER 任务专用 300 秒超时（给微重试充分缓冲）
                agent_role = current_task.get("agent_role")
                if agent_role == AgentRole.ENGINEER or str(agent_role).upper() == "ENGINEER":
                    timeout_seconds = int(settings.ADAMI_MULTI_AGENT_ENGINEER_WAIT_SEC)
                else:
                    timeout_seconds = max(
                        current_task.get(
                            "timeout_seconds", settings.ADAMI_MULTI_AGENT_DEFAULT_WAIT_SEC
                        ),
                        int(settings.ADAMI_MULTI_AGENT_MIN_WAIT_SEC),
                    )

                logger.info(
                    _orch_ui_t(
                        "orch.magent.log.timeout_set",
                        role=_agent_role_label(agent_role),
                        sec=timeout_seconds,
                    )
                )

                try:
                    result = await asyncio.wait_for(
                        self._distribute_and_wait(current_task, state), timeout=timeout_seconds
                    )
                except asyncio.TimeoutError:
                    # ====================== 【本次最终修复】超时竞态条件保护 + future 已不存在 + 上下文结果检查 ======================
                    key = f"{state.workflow_id}_{agent_role}"
                    future = self.task_futures.get(key)
                    if future is None:
                        # future 已被 _handle_agent_message pop，检查 context 中是否已有结果
                        role_key = (
                            agent_role.value.lower()
                            if hasattr(agent_role, "value")
                            else str(agent_role).lower()
                        )
                        if role_key in state.context:
                            logger.info(
                                _orch_ui_t(
                                    "orch.magent.log.timeout_ctx_ok",
                                    role=_agent_role_label(agent_role),
                                )
                            )
                            result = state.context[role_key]
                            # 直接继续正常流程（不重试），后续代码会推进 DAG
                        else:
                            logger.warning(
                                _orch_ui_t(
                                    "orch.magent.warn.timeout_retry",
                                    role=_agent_role_label(agent_role),
                                )
                            )
                            # 重试逻辑
                            retry_count = state.context.get(f"retry_{agent_role}", 0) + 1
                            state.context[f"retry_{agent_role}"] = retry_count
                            if retry_count <= 2:
                                continue
                            else:
                                hitl_reason = _orch_ui_t(
                                    "orch.hitl.reason_task_timeouts",
                                    agent_role=_agent_role_label(agent_role),
                                )
                                await self._hitl_pre_pause_phase(state, hitl_reason)
                                state.status = "PAUSED"
                                await self.memory.save_workflow_state(state)
                                if hitl_handler is not None:
                                    await hitl_handler.trigger_paused(
                                        state.workflow_id,
                                        state.chat_id,
                                        hitl_reason,
                                    )
                                else:
                                    logger.warning(_orch_ui_t("orch.magent.warn.hitl_none"))
                                break
                    else:
                        # future 还存在，正常重试
                        if future.done():
                            try:
                                result = future.result()
                                logger.info(
                                    _orch_ui_t("orch.magent.log.timeout_future_done", fkey=key)
                                )
                            except Exception as inner_e:
                                logger.warning(
                                    _orch_ui_t(
                                        "orch.magent.warn.timeout_future_err",
                                        e=inner_e,
                                    )
                                )
                        else:
                            logger.warning(
                                _orch_ui_t(
                                    "orch.magent.warn.timeout_threshold",
                                    role=_agent_role_label(agent_role),
                                    sec=timeout_seconds,
                                )
                            )
                            retry_key = f"retry_{agent_role}"
                            retry_count = state.context.get(retry_key, 0) + 1
                            state.context[retry_key] = retry_count

                            if retry_count <= 2:
                                continue
                            else:
                                hitl_reason = _orch_ui_t(
                                    "orch.hitl.reason_task_timeouts",
                                    agent_role=_agent_role_label(agent_role),
                                )
                                await self._hitl_pre_pause_phase(state, hitl_reason)
                                state.status = "PAUSED"
                                await self.memory.save_workflow_state(state)
                                if hitl_handler is not None:
                                    await hitl_handler.trigger_paused(
                                        state.workflow_id,
                                        state.chat_id,
                                        hitl_reason,
                                    )
                                else:
                                    logger.warning(_orch_ui_t("orch.magent.warn.hitl_none"))
                                break
                    # =================================================================================

                agent_role_str = current_task.get("agent_role")
                try:
                    role = (
                        AgentRole(agent_role_str)
                        if isinstance(agent_role_str, str)
                        else agent_role_str
                    )
                except ValueError:
                    role = agent_role_str
                key = role.value.lower() if hasattr(role, "value") else str(role).lower()
                state.context[key] = result

                # ====================== 【Step 3 新增】Researcher 成功后立即保存 checkpoint ======================
                if key == "researcher" and isinstance(result, dict):
                    await self._save_researcher_checkpoint(
                        state.workflow_id, result, workflow_state_version=state.version
                    )
                # =====================================================================

                dag = state.context["dag"]
                current_index = None
                for idx, t in enumerate(dag):
                    if t.get("task_id") == current_task.get("task_id"):
                        current_index = idx
                        break
                if current_index is None:
                    current_index = dag.index(current_task) if current_task in dag else -1
                if current_index is not None and current_index + 1 < len(dag):
                    next_task = dag[current_index + 1]
                    ar = next_task.get("agent_role")
                    next_key = ar.value.lower() if hasattr(ar, "value") else str(ar).lower()
                    await emit_phase_transition_if_changed(
                        state,
                        self.memory,
                        self.bus,
                        to_phase=long_task_phase_for_agent_role(next_key),
                        reason=f"multi_agent_handoff->{next_key}",
                        source_module="multi_agent_orchestrator",
                        gate_detail="role_switch",
                        history_extras={
                            "agent_role_completed": key,
                            "agent_role_next": next_key,
                        },
                    )
                    state.context["current_task"] = next_task
                    state.global_step_count += 1
                    await self.memory.save_workflow_state(state)
                else:
                    await emit_phase_transition_if_changed(
                        state,
                        self.memory,
                        self.bus,
                        to_phase=LongTaskPhase.DELIVER,
                        reason="multi_agent_terminal_success",
                        source_module="multi_agent_orchestrator",
                        gate_detail="workflow_terminal",
                        history_extras={"agent_role_completed": key},
                    )
                    state.status = "SUCCESS"
                    await self.memory.save_workflow_state(state)
                    logger.info(_orch_ui_t("orch.magent.log.workflow_done", wid=state.workflow_id))
                    break

            if future and not future.done():
                if state.status == "SUCCESS":
                    final_result = state.context
                    future.set_result(final_result)
                else:
                    future.set_exception(
                        Exception(
                            _orch_ui_t("orch.magent.error.workflow_ended", status=state.status)
                        )
                    )

        except Exception as e:
            logger.error(_orch_ui_t("orch.magent.err.orchestrate", e=e), exc_info=True)

            if self._record_workflow_error(state.workflow_id, e):
                logger.warning(_orch_ui_t("orch.magent.warn.circuit_pause", wid=state.workflow_id))
                hitl_reason = _orch_ui_t(
                    "orch.hitl.reason_circuit_errors",
                    error_type=type(e).__name__,
                )
                await self._hitl_pre_pause_phase(state, hitl_reason)
                state.status = "PAUSED"
                await self.memory.save_workflow_state(state)
                if hitl_handler is not None:
                    await hitl_handler.trigger_paused(
                        state.workflow_id,
                        state.chat_id,
                        hitl_reason,
                    )
                else:
                    logger.warning(_orch_ui_t("orch.magent.warn.hitl_none_short"))
            else:
                state.status = "FAILED"
                await self.memory.save_workflow_state(state)

            if future and not future.done():
                future.set_exception(e)
        finally:
            experience_episode_id_ctx.reset(tok_e)
            experience_primary_trace_ctx.reset(tok_p)
            sink = get_experience_sink()
            st = state.status
            if st == "SUCCESS":
                sink.end_episode(state.workflow_id, "success", pop_context=False)
            elif st == "FAILED":
                sink.end_episode(state.workflow_id, "failed", pop_context=False)
            elif st == "PAUSED":
                sink.end_episode(state.workflow_id, "paused", pop_context=False)
            self.workflow_futures.pop(state.workflow_id, None)
            self._error_fingerprints.pop(state.workflow_id, None)

    def register_agent(self, role: AgentRole, agent_instance: Any):
        if agent_instance is None:
            logger.warning(
                _orch_ui_t("orch.magent.warn.register_none", role=_agent_role_label(role))
            )
            return
        self.agents[role] = agent_instance
        logger.debug("[MultiAgentOrchestrator] agent registered: %s", role)

    async def pause_workflow(self, workflow_id: str):
        if workflow_id in self.active_orchestrations:
            state = self.active_orchestrations[workflow_id]
            await self._hitl_pre_pause_phase(state, "manual_pause")
            state.status = "PAUSED"
            await self.memory.save_workflow_state(state)
            logger.debug(_orch_ui_t("orch.magent.debug.workflow_paused", wid=workflow_id))

    async def resume_workflow(self, workflow_id: str):
        if workflow_id in self.active_orchestrations:
            state = self.active_orchestrations[workflow_id]
            state.status = "RUNNING"
            await checkpoint_hitl_boundary(
                state,
                self.memory,
                self.bus,
                kind="post_hitl_resume",
                reason="multi_agent_resume",
                source_module="multi_agent_orchestrator",
            )
            await self.memory.save_workflow_state(state)
            asyncio.create_task(self._orchestrate(state))
            logger.debug(_orch_ui_t("orch.magent.debug.workflow_resumed", wid=workflow_id))

    async def shutdown(self):
        if self._subscription_task and not self._subscription_task.done():
            self._subscription_task.cancel()
        logger.debug(_orch_ui_t("orch.magent.debug.shutdown"))


# --- END OF FILE src/adami_kernel/orchestrator/multi_agent_orchestrator.py ---
