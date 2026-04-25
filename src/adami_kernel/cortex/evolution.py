# src/adami_kernel/cortex/evolution.py
# 文件路径：src/adami_kernel/cortex/evolution.py
# 版本：v2.1（循环导入彻底修复版 + Agent Lightning 兼容）
# 修改时间：2026-04-07
# 修复目的：解决 evolution.py 与 skill_manager 之间的循环导入，导致 kernel 启动失败

from __future__ import annotations

import logging
import os
import re
import shutil
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from adami_kernel.config import settings
from adami_kernel.i18n import t as i18n_t
from adami_kernel.i18n.boot_msg import boot_t
from adami_kernel.integration.mcp_agent.contracts import (
    ToolContractRegistry,
    ToolInvocation,
    legacy_fragment_from_tool_schemas,
    to_llm_prompt_fragment,
    tool_capability_mcp,
    tool_capability_native,
)

logger = logging.getLogger("AdamI-Evolution")

if TYPE_CHECKING:
    from adami_kernel.cortex.dream_sandbox import DreamSandbox
    from adami_kernel.hippocampus.layered_memory import LayeredMemory
    from adami_kernel.skill_manager.skill_manager import SkillManager


def _cevo_t(key: str, **kwargs) -> str:
    return i18n_t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class EvolutionEngine:
    """
    AdamI 进化引擎 V6.3 (真实参数嗅探版)
    【本次核心修复】：使用 __init__ 内懒加载彻底解决与 skill_manager 的循环导入
    【本次新增】：Agent Lightning 兼容性准备（trace/reward 已预留位置）
    """

    def __init__(
        self,
        toolbox: Any = None,
        base_dir: Optional[str] = None,
        skill_manager: Optional[SkillManager] = None,
        memory: Optional[LayeredMemory] = None,
        dream_sandbox: Optional[DreamSandbox] = None,
    ):
        self.toolbox = toolbox
        self.dream_sandbox = dream_sandbox
        self.base_dir = os.path.abspath(
            base_dir if base_dir is not None else str(settings.adami_data_dir_path.resolve())
        )
        self.skills_dir = os.path.join(self.base_dir, "skills")
        self.instincts_dir = os.path.join(self.base_dir, "instincts")
        self.usage_file = os.path.join(self.base_dir, "skill_usage.json")
        self.sandbox_volume = os.path.join(self.base_dir, "sandbox_volume")
        os.makedirs(self.sandbox_volume, exist_ok=True)
        os.makedirs(self.instincts_dir, exist_ok=True)

        # ====================== 【关键修复】懒加载避免循环导入 ======================
        # 所有 skill_manager 依赖在此处延迟导入，彻底打破循环
        from adami_kernel.skill_manager.skill_builder import SkillBuilder
        from adami_kernel.skill_manager.skill_factory import SkillFactory
        from adami_kernel.skill_manager.skill_file_loader import SkillFileLoader
        from adami_kernel.skill_manager.skill_template import SKILL_TEMPLATE
        from adami_kernel.skill_manager.skill_usage_manager import SkillUsageManager
        # =========================================================================

        self.SKILL_TEMPLATE = SKILL_TEMPLATE

        self.code_generator = SkillFactory(
            toolbox.router if toolbox else None, dream_sandbox=dream_sandbox
        )
        self.memory = memory
        self.skill_builder = SkillBuilder(memory=self.memory, dream_sandbox=dream_sandbox)
        self.file_loader = SkillFileLoader(
            skills_dir=self.skills_dir,
            instincts_dir=self.instincts_dir,
            on_skill_loaded=self._on_skill_loaded_callback,
        )
        self.usage_manager = SkillUsageManager(
            usage_file=self.usage_file, on_threshold_reached=self._instinctualize
        )

        self.skill_manager = skill_manager

        self.tool_schemas: Dict[str, Dict[str, Any]] = {}
        self.tool_contract_registry = ToolContractRegistry()
        self.dynamic_skills = {}
        self.core_instincts = {}

        self.USAGE_THRESHOLD = 3
        self.cleanup_corrupted_skills()
        logger.info(boot_t("boot.log.evolution_loaded"))

    def _on_skill_loaded_callback(self, skill_name: str, module: Any, is_instinct: bool = False):
        if hasattr(module, "execute"):
            if not is_instinct and skill_name in self.core_instincts:
                logger.info(
                    boot_t("boot.log.evolution_skip_dynamic_shadow", name=skill_name),
                )
                return
            wrapped_exec = self.usage_manager.create_execute_wrapper(
                module.execute, skill_name, is_instinct=is_instinct
            )
            if is_instinct:
                self.dynamic_skills.pop(skill_name, None)
                self.core_instincts[skill_name] = wrapped_exec
            else:
                self.dynamic_skills[skill_name] = wrapped_exec

            # ====================== 【核心修复】自动嗅探真实参数 ======================
            properties = {}
            required = []
            try:
                skill_path = os.path.join(self.skills_dir, f"{skill_name.lower()}.py")
                if not os.path.exists(skill_path):
                    skill_path = os.path.join(self.instincts_dir, f"{skill_name.lower()}.py")

                if os.path.exists(skill_path):
                    with open(skill_path, "r", encoding="utf-8") as f:
                        code = f.read()
                    keys = set(re.findall(r'kwargs\.get\([\'"]([a-zA-Z0-9_]+)[\'"]', code))
                    for k in keys:
                        properties[k] = {
                            "type": "string",
                            "description": _cevo_t("cevo.schema.param", name=k),
                        }
                        required.append(k)
            except Exception as e:
                logger.warning(boot_t("boot.log.evolution_sniff_warn", detail=str(e)))

            if not properties:
                properties = {
                    "args": {
                        "type": "object",
                        "description": _cevo_t("cevo.schema.args"),
                    }
                }

            self.register_tool(
                skill_name,
                {"type": "object", "properties": properties, "required": required},
                _cevo_t("cevo.tool.dynamic", skill_name=skill_name),
            )
            logger.info(
                boot_t(
                    "boot.log.evolution_skill_registered",
                    name=skill_name,
                    params=repr(required),
                )
            )
            # =========================================================================

    def _instinctualize(self, skill_name: str):
        """【本次修复】大小写兼容固化路径检查"""
        src_upper = os.path.join(self.skills_dir, f"{skill_name.upper()}.py")
        src_lower = os.path.join(self.skills_dir, f"{skill_name.lower()}.py")
        src = src_upper if os.path.exists(src_upper) else src_lower
        dst = os.path.join(self.instincts_dir, f"{skill_name.upper()}.py")
        if not os.path.exists(src):
            logger.warning(_cevo_t("cevo.log.move_missing_src", src=src))
            return
        os.makedirs(self.instincts_dir, exist_ok=True)
        try:
            shutil.move(src, dst)
            logger.info(_cevo_t("cevo.log.instinct_ok", name=skill_name, src=src, dst=dst))
            if skill_name in self.dynamic_skills:
                self.core_instincts[skill_name] = self.dynamic_skills.pop(skill_name)
        except Exception as e:
            logger.error(_cevo_t("cevo.err.instinct", e=e))

    def get_persona_additions(self) -> str:
        additions = []
        instincts_list = [
            f[:-3].upper()
            for f in os.listdir(self.instincts_dir)
            if f.endswith(".py") and not f.startswith("__")
        ]
        if instincts_list:
            additions.append(_cevo_t("cevo.persona.instincts", names=", ".join(instincts_list)))
        skills_list = [
            f[:-3].upper()
            for f in os.listdir(self.skills_dir)
            if f.endswith(".py") and not f.startswith("__")
        ]
        if skills_list:
            additions.append(_cevo_t("cevo.persona.skills", names=", ".join(skills_list)))
        if self.tool_schemas:
            additions.append(self.get_registered_tools_for_llm())
        return "\n".join(additions) if additions else ""

    def register_tool(
        self,
        name: str,
        json_schema: dict,
        description: str = "",
        *,
        sync_contract: bool = True,
        tool_source: str = "native",
        mcp_server: Optional[str] = None,
        mcp_tool_name: Optional[str] = None,
    ) -> None:
        name = name.upper()
        required = json_schema.get("required", [])
        if not required and "properties" in json_schema:
            required = list(json_schema["properties"].keys())
        self.tool_schemas[name] = {
            "json_schema": json_schema,
            "description": description,
            "required_params": required,
        }
        if sync_contract:
            if tool_source == "mcp" and mcp_server and mcp_tool_name is not None:
                self.tool_contract_registry.register(
                    tool_capability_mcp(
                        name,
                        json_schema,
                        description,
                        mcp_server,
                        mcp_tool_name,
                    )
                )
            else:
                self.tool_contract_registry.register(
                    tool_capability_native(name, json_schema, description)
                )
        logger.info(boot_t("boot.log.tool_registry_registered", name=name, params=repr(required)))

    def get_tool_schema(self, name: str) -> Optional[Dict]:
        return self.tool_schemas.get(name.upper())

    def get_tool_required_params(self, name: str) -> List[str]:
        tool = self.tool_schemas.get(name.upper())
        return tool.get("required_params", []) if tool else []

    def get_registered_tools_for_llm(self) -> str:
        exposed = self.tool_contract_registry.list_exposed_sorted()
        if exposed:
            return to_llm_prompt_fragment(exposed)
        if not self.tool_schemas:
            return ""
        return legacy_fragment_from_tool_schemas(self.tool_schemas)

    def get_all_skills(self) -> List[Dict[str, Any]]:
        skills = []
        usage_data = self.usage_manager._get_usage()

        for name in self.core_instincts.keys():
            stats = usage_data.get(name, {"count": 0, "last_used": None})
            skills.append(
                {
                    "name": name,
                    "status": "active",
                    "type": "instinct",
                    "usage": stats.get("count", 0),
                    "last_used": stats.get("last_used", _cevo_t("cevo.last_used_unknown")),
                }
            )
        for name in self.dynamic_skills.keys():
            stats = usage_data.get(name, {"count": 0, "last_used": None})
            skills.append(
                {
                    "name": name,
                    "status": "active",
                    "type": "dynamic",
                    "usage": stats.get("count", 0),
                    "last_used": stats.get("last_used", _cevo_t("cevo.last_used_unknown")),
                }
            )

        if not skills:
            for name in self.core_instincts.keys():
                skills.append(
                    {
                        "name": name,
                        "status": "active",
                        "type": "instinct",
                        "usage": 0,
                        "last_used": _cevo_t("cevo.last_used_unknown"),
                    }
                )
            for name in self.dynamic_skills.keys():
                skills.append(
                    {
                        "name": name,
                        "status": "active",
                        "type": "dynamic",
                        "usage": 0,
                        "last_used": _cevo_t("cevo.last_used_unknown"),
                    }
                )

        return skills

    async def load_genetic_skills(self) -> None:
        await self.file_loader.load_genetic_skills()

    def cleanup_corrupted_skills(self):
        self.file_loader.cleanup_corrupted_skills()

    async def create_new_skill(
        self, *args, skip_inspection: bool = False, **kwargs
    ) -> Dict[str, Any]:
        payload = kwargs
        for arg in args:
            if isinstance(arg, dict):
                payload.update(arg)

        skill_name = self.sanitize_skill_name(
            payload.get("skill_name", payload.get("name", "TEMP_SKILL"))
        )
        description = payload.get(
            "description",
            payload.get("task_description", _cevo_t("cevo.desc.missing")),
        )

        raw_code = await self.code_generator.generate_code(description, skill_name)
        if not raw_code or not raw_code.strip():
            return {"status": "error", "error": _cevo_t("cevo.err.empty_code")}

        file_path, validation_result = await self.skill_builder.build(raw_code, skill_name)

        if not validation_result.passed:
            error_msg = _cevo_t("cevo.err.build_fmt", detail=str(validation_result))
            logger.error(_cevo_t("cevo.err.build_wrap", detail=error_msg))
            return {
                "status": "error",
                "error": error_msg,
                "validation_errors": validation_result.errors,
            }

        await self.file_loader.load_from_directory(self.skills_dir, is_instinct=False)

        if self.skill_manager and hasattr(self.skill_manager, "set_lifecycle_status"):
            from adami_kernel.skill_manager.skill_lifecycle import SkillStatus as _SkillStatus

            self.skill_manager.set_lifecycle_status(skill_name, _SkillStatus.ACTIVE)

        return {
            "status": "success",
            "data": {
                "message": _cevo_t("cevo.msg.hatch_ok", skill_name=skill_name),
                "skill_path": file_path,
                "skill_name": skill_name,
            },
            "error": None,
        }

    def sanitize_skill_name(self, name: str) -> str:
        if not name:
            return "TEMP_SKILL"
        cleaned = "".join(c for c in name if c.isalnum() or c in "_")
        return cleaned.upper() if cleaned else "TEMP_SKILL"

    def get_skill(self, name: str):
        name = name.upper()
        f = self.core_instincts.get(name) or self.dynamic_skills.get(name)
        if f:
            return f
        # 外部工具执行兜底：当工具注册在 ToolboxManager.external_executors 中时，也允许按技能调用路径执行
        tb = getattr(self, "toolbox", None)
        if tb and hasattr(tb, "execute_tool"):

            async def _exec(**kwargs: Any) -> Any:
                return await tb.execute_tool(name, kwargs)

            return _exec
        return None

    async def execute_tool_dispatch(
        self,
        tool_id: str,
        args: Dict[str, Any],
        *,
        trace_id: str = "",
        chat_id: str = "",
    ) -> Any:  # noqa: ANN401
        """契约层优先；``ADAMI_USE_MCP_AGENT`` 时 MCP 工具经 mcp-agent 会话执行，失败回退 ``get_skill``。"""
        from adami_kernel.telemetry.experience_sink import (
            get_experience_sink,
            infer_tool_audit_meta,
            redact_payload,
            summarize_text,
        )

        tid = (tool_id or "").upper().strip()
        raw_args = dict(args or {})
        inv = ToolInvocation(
            tool_id=tid,
            args=raw_args,
            trace_id=trace_id or "",
            chat_id=chat_id or "",
        )
        cap = self.tool_contract_registry.get(tid)

        t0 = time.perf_counter()
        holder: Dict[str, Any] = {"value": None, "err": None}
        audit_backend: Optional[str] = None

        try:
            if cap is not None:
                from adami_kernel.integration.mcp_agent.tool_executor import (
                    try_execute_via_mcp_agent,
                )

                pilot = await try_execute_via_mcp_agent(inv, cap)
                if pilot is not None:
                    holder["value"] = pilot
                    audit_backend = "mcp_agent"
                    return pilot

            skill = self.get_skill(tid)
            if skill:
                out = await skill(**raw_args)
                holder["value"] = out
                if audit_backend is None:
                    audit_backend = "mcp_docker" if cap and cap.source == "mcp" else "native"
                return out
            err = ValueError(f"No skill or tool registered for action: {tid}")
            holder["err"] = err
            raise err
        except Exception as e:
            if holder["err"] is None:
                holder["err"] = e
            raise
        finally:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            ok = holder["err"] is None
            err_t = type(holder["err"]).__name__ if holder["err"] else None
            res_val = holder["value"]
            if not ok and res_val is None and holder["err"] is not None:
                res_val = str(holder["err"])
            args_sum = summarize_text(str(redact_payload(raw_args)))
            res_sum = summarize_text(str(redact_payload(res_val if res_val is not None else "")))
            meta = infer_tool_audit_meta(self, tid, override_backend=audit_backend)
            get_experience_sink().record_tool_call(
                trace_id=trace_id or tid,
                tool_name=tid,
                tool_id=meta["tool_id"],
                args_summary=args_sum,
                result_summary=res_sum,
                error_code=err_t if not ok else None,
                ok=ok,
                tool_backend=meta["tool_backend"],
                latency_ms=elapsed_ms,
                docker_used=meta["docker_used"],
                mcp_allow_deny=meta["mcp_allow_deny"],
                extra={"chat_id": chat_id, "path": "evolution.execute_tool_dispatch"},
            )

    async def execute_with_retry(
        self,
        action: str,
        args: Dict[str, Any],
        *,
        trace_id: str = "",
        chat_id: str = "",
        max_retries: int = 2,
    ) -> Any:  # noqa: ANN401
        """TaskPlanner 规划步骤执行入口（兼容历史名）：带轻量重试。"""
        import asyncio

        last_err: Optional[Exception] = None
        for attempt in range(max(1, int(max_retries))):
            try:
                return await self.execute_tool_dispatch(
                    action, args, trace_id=trace_id, chat_id=chat_id
                )
            except Exception as e:
                last_err = e
                if attempt + 1 < max_retries:
                    await asyncio.sleep(0.4 * (attempt + 1))
        if last_err is not None:
            raise last_err
        raise RuntimeError("execute_with_retry: no error after failed attempts")

    async def evolve_skill(self, *args, **kwargs) -> Dict[str, Any]:
        return await self.create_new_skill(*args, **kwargs)

    async def melt_skill(self, raw_code: str, skill_name: str) -> str:
        return raw_code

    async def install_from_market(
        self, skill_name: str, repo_url: Optional[str] = None
    ) -> Dict[str, Any]:
        return {"status": "error", "error": _cevo_t("cevo.err.market")}
