# 文件路径：src/adami_kernel/orchestrator/skill_composer.py
# 版本：v2.10（AGL 统一 agl_compat；CREATE_NEW_SKILL 解析与超时逻辑同 v2.9）
# 修改时间：2026-04-08

import json
import logging
import re
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("AdamI-SkillComposer")

from adami_kernel.config import settings
from adami_kernel.cortex.router import LLMRouter
from adami_kernel.cortex.tools.json_parser import (
    extract_json_and_python_code,
    extract_json_from_llm_output,
)
from adami_kernel.cortex.tools_manager import ToolboxManager
from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.i18n import t
from adami_kernel.observability.agl_compat import agl, get_trace_context
from adami_kernel.orchestrator.workflow_models import Node, WorkflowState, ensure_default_profile_id
from adami_kernel.telemetry.experience_sink import get_experience_sink


def _composer_node_timeout(*, kind: str) -> int:
    if kind == "llm":
        return int(getattr(settings, "ADAMI_WORKFLOW_LLM_NODE_TIMEOUT", 300))
    if kind == "skill_build":
        return int(getattr(settings, "ADAMI_WORKFLOW_SKILL_BUILD_TIMEOUT", 300))
    return int(getattr(settings, "ADAMI_SKILL_TIMEOUT", 60))


def _sc_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


def _tag_skill_composer_profile(state: WorkflowState) -> WorkflowState:
    """Orchestration-only default ``profile_id``; does not overwrite caller-set values."""
    ensure_default_profile_id(state, "skill_composer")
    return state


# ====================== 【OTEL 完全防御】 ======================
try:
    from adami_kernel.observability.otel import start_span
except (ImportError, ModuleNotFoundError):
    logger.debug(_sc_t("skcp.log.otel_noop"))

    @contextmanager
    def start_span(name: str):
        logger.debug(_sc_t("skcp.log.otel_span", name=name))
        yield
# =================================================================


class SkillComposer:
    """
    技能组合器：根据任务描述和可用技能，生成一个可执行的工作流 DAG。
    【v2.7 核心修复】：logger 定义顺序修正 + 完整 DummyAgl（全系统 AGL 统一）
    """

    def __init__(
        self,
        router: LLMRouter,
        memory: LayeredMemory,
        toolbox: ToolboxManager,
        skill_router: Optional = None,
    ):
        self.router = router
        self.memory = memory
        self.toolbox = toolbox
        self.skill_router = skill_router

        # ====================== 【延迟导入 SkillRouter，阻断 OTEL 错误链】 ======================
        if self.skill_router is None:
            try:
                from adami_kernel.skill_manager.skill_router import SkillRouter

                self.skill_router = SkillRouter()
            except Exception as e:
                logger.warning(_sc_t("skcp.warn.router_import", e=e))
                self.skill_router = None
        # =================================================================================

        logger.debug("[SkillComposer] initialized")

    def _extract_create_new_skill_payload(
        self, llm_response: str
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        action, code = extract_json_and_python_code(llm_response)
        if not action:
            logger.warning(_sc_t("skcp.warn.no_action_json"))
            json_match = re.search(r"(\{[\s\S]*?\})", llm_response, re.DOTALL)
            if json_match:
                try:
                    action = json.loads(json_match.group(1))
                except Exception:
                    pass
        if not action:
            action = extract_json_from_llm_output(llm_response)

        if code and not action:
            logger.warning(_sc_t("skcp.warn.py_no_json"))
            action = {
                "action": "CREATE_NEW_SKILL",
                "args": {"skill_name": "AUTO_COMPOSED", "description": ""},
            }

        if action and isinstance(action, dict) and action.get("action") != "CREATE_NEW_SKILL":
            action["action"] = "CREATE_NEW_SKILL"

        if action and code:
            logger.info(
                _sc_t(
                    "skcp.log.extract_ok",
                    action=action.get("action"),
                    code_length=len(code),
                )
            )
        elif action:
            logger.warning(_sc_t("skcp.warn.action_only_json"))
        else:
            logger.error(_sc_t("skcp.err.extract_fail"))

        return action, code

    def _is_valid_condition(self, expr: str) -> bool:
        if not isinstance(expr, str):
            return False
        if re.search(r"[\u4e00-\u9fff]", expr):
            logger.debug(_sc_t("skcp.debug.cond_han", expr=expr))
            return False
        if re.search(r"[，。？！；、]", expr):
            logger.debug(_sc_t("skcp.debug.cond_punct", expr=expr))
            return False
        safe_expr = re.sub(r"\$context\.[a-zA-Z0-9_.]+", "dummy", expr)
        try:
            compile(safe_expr, "<string>", "eval")
            return True
        except SyntaxError:
            logger.debug(_sc_t("skcp.debug.cond_syntax", expr=expr))
            return False

    def _repair_condition(self, condition: str, node_id: str, edges: Dict[str, List[str]]) -> str:
        if not condition:
            return condition
        stripped = condition.lstrip()
        if stripped.startswith(("==", "!=", ">", "<", ">=", "<=")):
            predecessor = None
            for src, targets in edges.items():
                if node_id in targets:
                    predecessor = src
                    break
            if predecessor:
                repaired = f"$context.{predecessor}.status {stripped}"
            else:
                repaired = f"$context.{node_id}.status {stripped}"
            if self._is_valid_condition(repaired):
                logger.info(_sc_t("skcp.log.cond_repair", old=condition, new=repaired))
                return repaired
            else:
                logger.warning(_sc_t("skcp.warn.cond_repair_fail", condition=condition))
                return "False"
        return condition

    @staticmethod
    def _non_empty_next(value: object) -> Optional[str]:
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None

    def _fix_condition_node_branches(self, nodes: List[Dict], edges: Dict[str, List[str]]) -> None:
        """保证 CONDITION 的 true_next/false_next 均有可用目标，避免运行期缺边。"""
        for node_def in nodes:
            if node_def.get("node_type") != "CONDITION":
                continue
            node_id = node_def.get("node_id")
            config = node_def.setdefault("config", {})
            successors = edges.get(node_id, []) or []

            tn = self._non_empty_next(config.get("true_next"))
            fn = self._non_empty_next(config.get("false_next"))

            if tn and fn:
                config["true_next"], config["false_next"] = tn, fn
                continue

            if not successors:
                logger.warning(_sc_t("skcp.warn.cond_no_successors", node_id=node_id))
                if tn:
                    config["true_next"], config["false_next"] = tn, tn
                elif fn:
                    config["true_next"], config["false_next"] = fn, fn
                else:
                    config["true_next"] = None
                    config["false_next"] = None
                continue

            if not tn and not fn:
                default_next = successors[0]
                config["true_next"] = default_next
                config["false_next"] = successors[1] if len(successors) > 1 else default_next
                logger.info(_sc_t("skcp.log.cond_fill_branches", node_id=node_id, nxt=default_next))
                continue

            if tn and not fn:
                config["false_next"] = successors[1] if len(successors) > 1 else tn
                logger.info(
                    _sc_t(
                        "skcp.log.cond_branch_patch",
                        node_id=node_id,
                        tn=tn,
                        fn=config["false_next"],
                    )
                )
            elif fn and not tn:
                config["true_next"] = successors[0] if successors else fn
                logger.info(
                    _sc_t(
                        "skcp.log.cond_branch_patch",
                        node_id=node_id,
                        tn=config["true_next"],
                        fn=fn,
                    )
                )

    async def _create_fallback_workflow(self, task_description: str) -> WorkflowState:
        logger.info(_sc_t("skcp.log.fallback_workflow"))
        with get_trace_context(
            trace_id=f"skill_composer_fallback_{int(time.time())}",
            task_description=task_description,
            metadata={"intent": "fallback"},
        ) as trace:
            try:
                with start_span("skill_composer.fallback_workflow") as span:
                    if hasattr(span, "set_attribute"):
                        span.set_attribute("task_description", task_description)

                    if self.skill_router and not self.skill_router.is_skill_creation_task(
                        task_description
                    ):
                        try:
                            result = await self.skill_router.get_call_spec(task_description)
                            if result:
                                skill_name, _ = result
                                agl.emit_reward(
                                    trace_id=trace.trace_id,
                                    reward=1.0,
                                    metadata={"fallback": "skill_call"},
                                )
                                get_experience_sink().record_feedback(
                                    trace_id=trace.trace_id,
                                    reward=1.0,
                                    metadata={"fallback": "skill_call"},
                                    source="skill_composer",
                                )
                                return _tag_skill_composer_profile(
                                    WorkflowState(
                                        chat_id="system",
                                        status="PENDING",
                                        context={"original_task": task_description},
                                        nodes={
                                            "node1": Node(
                                                node_id="node1",
                                                node_type="SKILL_CALL",
                                                config={"skill_name": skill_name, "args": {}},
                                                description=_sc_t(
                                                    "sc.node.desc.invoke_skill",
                                                    skill_name=skill_name,
                                                ),
                                                timeout=_composer_node_timeout(kind="default"),
                                            )
                                        },
                                        edges={"node1": []},
                                    )
                                )
                        except Exception as inner_e:
                            logger.warning(_sc_t("skcp.warn.fallback_call_spec", err=inner_e))

                    agl.emit_reward(
                        trace_id=trace.trace_id, reward=0.5, metadata={"fallback": "llm_call"}
                    )
                    get_experience_sink().record_feedback(
                        trace_id=trace.trace_id,
                        reward=0.5,
                        metadata={"fallback": "llm_call"},
                        source="skill_composer",
                    )
                    return _tag_skill_composer_profile(
                        WorkflowState(
                            chat_id="system",
                            status="PENDING",
                            context={"original_task": task_description},
                            nodes={
                                "node1": Node(
                                    node_id="node1",
                                    node_type="LLM_CALL",
                                    config={
                                        "prompt": _sc_t(
                                            "sc.node.prompt.handle_task",
                                            task_description=task_description,
                                        )
                                    },
                                    description=_sc_t("sc.node.desc.llm"),
                                    timeout=_composer_node_timeout(kind="llm"),
                                )
                            },
                            edges={"node1": []},
                        )
                    )
            except Exception as e:
                logger.error(_sc_t("skcp.err.fallback_workflow", e=e), exc_info=True)
                agl.emit_reward(trace_id=trace.trace_id, reward=0.0, metadata={"fallback": "error"})
                get_experience_sink().record_feedback(
                    trace_id=trace.trace_id,
                    reward=0.0,
                    metadata={"fallback": "error"},
                    source="skill_composer",
                )
                return _tag_skill_composer_profile(
                    WorkflowState(
                        chat_id="system",
                        status="PENDING",
                        context={"original_task": task_description},
                        nodes={
                            "node1": Node(
                                node_id="node1",
                                node_type="LLM_CALL",
                                config={
                                    "prompt": _sc_t(
                                        "sc.node.prompt.handle_task",
                                        task_description=task_description,
                                    )
                                },
                                description=_sc_t("sc.node.desc.llm_final"),
                                timeout=_composer_node_timeout(kind="llm"),
                            )
                        },
                        edges={"node1": []},
                    )
                )

    async def compose_workflow(
        self, task_description: str, available_skills: List[str]
    ) -> Optional[WorkflowState]:
        with get_trace_context(
            trace_id=f"skill_composer_{int(time.time())}",
            task_description=task_description,
            metadata={"available_skills_count": len(available_skills)},
        ) as trace:
            if self.skill_router and self.skill_router.is_skill_creation_task(task_description):
                logger.info(_sc_t("skcp.log.unified_create"))

                prompt = _sc_t("sc.prompt.create_new_skill", task_description=task_description)
                response = await self.router.call_llm(
                    prompt, brain_type="think", temperature=0.1, max_tokens=4096
                )

                action, python_code = self._extract_create_new_skill_payload(response)

                if not action or not python_code:
                    logger.error(_sc_t("skcp.err.create_extract_fail"))
                    return await self._create_fallback_workflow(task_description)

                agl.emit_reward(
                    trace_id=trace.trace_id, reward=1.0, metadata={"intent": "create_new_skill"}
                )
                get_experience_sink().record_feedback(
                    trace_id=trace.trace_id,
                    reward=1.0,
                    metadata={"intent": "create_new_skill"},
                    source="skill_composer",
                )

                state = WorkflowState(
                    chat_id="system",
                    status="PENDING",
                    context={"original_task": task_description, "extracted_code": python_code},
                    nodes={
                        "research": Node(
                            node_id="research",
                            node_type="LLM_CALL",
                            config={
                                "prompt": _sc_t("sc.node.prompt.research"),
                                "brain_type": "think",
                            },
                            description=_sc_t("sc.node.desc.research"),
                            timeout=_composer_node_timeout(kind="llm"),
                        ),
                        "engineer": Node(
                            node_id="engineer",
                            node_type="LLM_CALL",
                            config={
                                "prompt": _sc_t("sc.node.prompt.engineer"),
                                "brain_type": "think",
                            },
                            description=_sc_t("sc.node.desc.engineer"),
                            timeout=_composer_node_timeout(kind="llm"),
                        ),
                        "executor": Node(
                            node_id="executor",
                            node_type="SKILL_CALL",
                            config={"skill_name": "__TEMP__", "args": {"code": python_code}},
                            description=_sc_t("sc.node.desc.executor"),
                            timeout=_composer_node_timeout(kind="skill_build"),
                        ),
                        "critic": Node(
                            node_id="critic",
                            node_type="LLM_CALL",
                            config={
                                "prompt": _sc_t("sc.node.prompt.critic"),
                                "brain_type": "think",
                            },
                            description=_sc_t("sc.node.desc.critic"),
                            timeout=_composer_node_timeout(kind="llm"),
                        ),
                    },
                    edges={
                        "research": ["engineer"],
                        "engineer": ["executor"],
                        "executor": ["critic"],
                        "critic": [],
                    },
                )
                logger.info(_sc_t("skcp.log.create_dag_ok"))
                return _tag_skill_composer_profile(state)

            # 普通工作流生成逻辑（保持原有完整流程）
            skills_block = (
                ", ".join(available_skills) if available_skills else _sc_t("sc.compose.no_skills")
            )
            prompt = _sc_t(
                "sc.prompt.compose_workflow",
                task_description=task_description,
                skills_block=skills_block,
            )

            max_retries = 2
            for attempt in range(max_retries):
                try:
                    response = await self.router.call_llm(
                        prompt, brain_type="think", temperature=0.2
                    )
                except Exception as e:
                    logger.error(_sc_t("skcp.err.llm", e=e))
                    return await self._create_fallback_workflow(task_description)

                try:
                    data = json.loads(response)
                except json.JSONDecodeError:
                    match = re.search(r"\{.*\}", response, re.DOTALL)
                    if match:
                        try:
                            data = json.loads(match.group())
                        except json.JSONDecodeError as e:
                            logger.error(_sc_t("skcp.err.json_decode", e=e))
                            if attempt == max_retries - 1:
                                return await self._create_fallback_workflow(task_description)
                            continue
                    else:
                        logger.error(_sc_t("skcp.err.no_json_in_response"))
                        if attempt == max_retries - 1:
                            return await self._create_fallback_workflow(task_description)
                        continue
                except Exception as e:
                    logger.error(_sc_t("skcp.err.json_unknown", e=e))
                    return await self._create_fallback_workflow(task_description)

                if not isinstance(data, dict):
                    logger.error(_sc_t("skcp.err.not_json_object", typ=type(data)))
                    if attempt == max_retries - 1:
                        return await self._create_fallback_workflow(task_description)
                    continue
                if "nodes" not in data or not isinstance(data["nodes"], list):
                    logger.error(_sc_t("skcp.err.no_nodes_field"))
                    if attempt == max_retries - 1:
                        return await self._create_fallback_workflow(task_description)
                    continue
                if "edges" not in data or not isinstance(data["edges"], dict):
                    logger.warning(_sc_t("skcp.warn.no_edges_field"))
                    data["edges"] = {}

                edges = data.get("edges", {})
                for node_def in data.get("nodes", []):
                    if node_def.get("node_type") == "CONDITION":
                        node_id = node_def.get("node_id", "unknown")
                        config = node_def.get("config", {})
                        condition = config.get("condition", "")
                        if condition:
                            repaired = self._repair_condition(condition, node_id, edges)
                            config["condition"] = repaired

                self._fix_condition_node_branches(data["nodes"], edges)

                invalid_conditions = []
                for node_def in data.get("nodes", []):
                    if node_def.get("node_type") == "CONDITION":
                        condition = node_def.get("config", {}).get("condition", "")
                        if not self._is_valid_condition(condition):
                            invalid_conditions.append(node_def.get("node_id", "unknown"))
                            logger.warning(
                                _sc_t(
                                    "skcp.warn.node_bad_condition",
                                    node_id=node_def.get("node_id"),
                                    condition=condition,
                                )
                            )

                if invalid_conditions:
                    logger.warning(
                        _sc_t(
                            "skcp.warn.invalid_conditions_retry",
                            count=len(invalid_conditions),
                            attempt=attempt + 1,
                            max_retries=max_retries,
                        )
                    )
                    if attempt == max_retries - 1:
                        logger.error(_sc_t("skcp.err.conditions_abort"))
                        return await self._create_fallback_workflow(task_description)

                    prompt = _sc_t(
                        "sc.prompt.compose_retry",
                        task_description=task_description,
                        skills_block=skills_block,
                    )
                    continue

                state = WorkflowState(
                    chat_id="system",
                    status="PENDING",
                    context={},
                    nodes={},
                    edges=data.get("edges", {}),
                )
                for node_def in data.get("nodes", []):
                    if not isinstance(node_def, dict):
                        logger.warning(_sc_t("skcp.warn.node_not_dict"))
                        continue
                    if "node_id" not in node_def or "node_type" not in node_def:
                        logger.warning(_sc_t("skcp.warn.node_missing_fields"))
                        continue
                    raw_type = str(node_def.get("node_type") or "").strip().upper()
                    allowed_types = {
                        "LLM",
                        "TOOL",
                        "CONDITION",
                        "HUMAN",
                        "START",
                        "END",
                        "SKILL_CALL",
                        "LLM_CALL",
                    }
                    # SkillComposer 普通 DAG 可能返回角色型节点（ENGINEER/RESEARCHER/CRITIC/EXECUTOR）。
                    # WorkflowEngine 只理解 Node.node_type 的强类型集合，因此在此处做归一化映射。
                    if raw_type in ("ENGINEER", "RESEARCHER", "CRITIC", "PLANNER"):
                        node_type = "LLM_CALL"
                    elif raw_type in ("EXECUTOR",):
                        cfg = node_def.get("config", {}) or {}
                        node_type = (
                            "SKILL_CALL"
                            if isinstance(cfg, dict) and cfg.get("skill_name")
                            else "LLM_CALL"
                        )
                    elif raw_type in allowed_types:
                        node_type = raw_type
                    else:
                        logger.warning(_sc_t("skcp.warn.unknown_node_type", raw_type=raw_type))
                        node_type = "LLM_CALL"

                    config = node_def.get("config", {}) or {}
                    if not isinstance(config, dict):
                        config = {}
                    # 对 LLM_CALL 做最小补齐，避免 prompt 为空导致运行时无意义调用
                    if node_type in ("LLM", "LLM_CALL"):
                        if not config.get("prompt"):
                            # 优先使用 description，其次用 node_id/原始类型构造一个可诊断提示
                            fallback_prompt = (
                                node_def.get("description")
                                or f"Execute step {node_def.get('node_id')} ({raw_type}) for task: {task_description}"
                            )
                            config["prompt"] = str(fallback_prompt)
                    node = Node(
                        node_id=node_def["node_id"],
                        node_type=node_type,
                        config=config,
                        description=node_def.get("description", ""),
                    )
                    state.nodes[node.node_id] = node

                if not state.nodes:
                    logger.error(_sc_t("skcp.err.no_valid_nodes"))
                    return await self._create_fallback_workflow(task_description)

                logger.info(_sc_t("skcp.log.workflow_generated", n=len(state.nodes)))
                agl.emit_reward(
                    trace_id=trace.trace_id, reward=1.0, metadata={"intent": "compose_workflow"}
                )
                get_experience_sink().record_feedback(
                    trace_id=trace.trace_id,
                    reward=1.0,
                    metadata={"intent": "compose_workflow"},
                    source="skill_composer",
                )
                return _tag_skill_composer_profile(state)

            agl.emit_reward(
                trace_id=trace.trace_id,
                reward=0.5,
                metadata={"intent": "compose_workflow_fallback"},
            )
            get_experience_sink().record_feedback(
                trace_id=trace.trace_id,
                reward=0.5,
                metadata={"intent": "compose_workflow_fallback"},
                source="skill_composer",
            )
            return await self._create_fallback_workflow(task_description)
