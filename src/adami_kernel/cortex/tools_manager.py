import asyncio
import importlib
import logging
import os
import shlex
import sys
import time
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, Optional

if TYPE_CHECKING:
    from adami_kernel.integration.mcp_agent.contracts import ToolContractRegistry

from adami_kernel.config import settings
from adami_kernel.cortex.multi_modal import MultiModalInput
from adami_kernel.cortex.tools.fs_tool import FileSystemTool
from adami_kernel.cortex.tools.web_tool import WebTool
from adami_kernel.i18n import t as i18n_t

logger = logging.getLogger("CortexToolboxManager")


def _tlsm_t(key: str, **kwargs: object) -> str:
    return i18n_t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class ToolboxManager:
    def __init__(self, sandbox_dir: str = ".adami_sandbox"):
        self.sandbox_dir = os.path.abspath(sandbox_dir)
        self.venv_dir = os.path.join(self.sandbox_dir, ".venv")
        os.makedirs(self.sandbox_dir, exist_ok=True)

        self.fs = FileSystemTool(self.sandbox_dir)
        self.web = WebTool(self.sandbox_dir)

        # === 关键修复：兼容 Planner 调用 web_search ===
        self.web.web_search = self.web.search

        # 严格定义自我修改的物理边界
        self.allowed_patch_dir = os.path.abspath("src/adami_kernel/cortex/tools")

        # ====================== 多模态处理器 ======================
        self.multi_modal = MultiModalInput(router=None, toolbox=self)
        self.router = None  # 后续由 kernel 注入

        # ====================== 外部工具注册（MCP 等） ======================
        # tool_name(UPPER) -> schema/description
        self._external_tool_schemas: Dict[str, Dict[str, Any]] = {}
        # tool_name(UPPER) -> executor coroutine/callable
        self._external_executors: Dict[str, Callable[..., Awaitable[Any]]] = {}

        # Optional EventBus publisher: publish(AdamiEvent) -> bool
        self._event_publisher: Optional[Callable[[Any], Awaitable[bool]]] = None

    def set_event_publisher(self, publish: Callable[[Any], Awaitable[bool]] | None) -> None:
        self._event_publisher = publish

    async def _emit_tool_event(
        self,
        *,
        trace_id: Optional[str],
        source_module: str,
        payload: Dict[str, Any],
    ) -> None:
        if self._event_publisher is None:
            return
        from adami_kernel.nexus.event import AdamiEvent, EventPriority
        from adami_kernel.observability.tool_call_context import get_tool_trace_id

        tid = (trace_id or get_tool_trace_id() or "").strip() or "tool.unknown"
        try:
            await self._event_publisher(
                AdamiEvent(
                    trace_id=tid,
                    source_module=source_module,
                    target_topic="system.events",
                    priority=EventPriority.NORMAL,
                    payload=payload,
                )
            )
        except Exception:
            return

    def set_router(self, router):
        """Kernel 启动时动态注入 router（供 MultiModalInput + 新技能使用）"""
        self.router = router
        if hasattr(self.multi_modal, "set_router"):
            self.multi_modal.set_router(router)
        logger.debug("[Toolbox] multimodal + ANALYZE_RAW_MEDIA wired to router")

    def register_external_tools(
        self,
        source: str,
        tools: list[Dict[str, Any]],
        executors: Dict[str, Callable[..., Awaitable[Any]]],
        *,
        contract_registry: Optional["ToolContractRegistry"] = None,
        sync_contract: bool = True,
    ) -> None:
        """注册外部工具（例如 MCP）到 ToolboxManager。

        说明：Tool Registry（给 Planner 看）仍建议由 EvolutionEngine.register_tool 维护；
        这里主要负责“执行路由 + 工具列表聚合”。
        可选 ``contract_registry``：仅当工具**未**已在契约表中时写入（避免 MCP 双写）。
        """
        from adami_kernel.integration.mcp_agent.contracts import (
            tool_capability_external,
            tool_capability_mcp,
        )

        for t in tools or []:
            name = str(t.get("name") or "").upper().strip()
            if not name:
                continue
            self._external_tool_schemas[name] = {
                "source": source,
                "json_schema": t.get("json_schema", {}) or {},
                "description": t.get("description", "") or "",
            }
            if (
                sync_contract
                and contract_registry is not None
                and contract_registry.get(name) is None
            ):
                desc = str(t.get("description", "") or "")
                schema = t.get("json_schema", {}) or {}
                if str(source).startswith("mcp:"):
                    srv = str(source).split(":", 1)[1]
                    contract_registry.register(
                        tool_capability_mcp(
                            name,
                            schema,
                            desc,
                            srv,
                            str(t.get("mcp_tool_name") or name.split(".")[-1].lower()),
                        )
                    )
                else:
                    contract_registry.register(
                        tool_capability_external(name, schema, desc),
                    )
        for k, fn in (executors or {}).items():
            key = str(k).upper().strip()
            if not key:
                continue
            self._external_executors[key] = fn

    def unregister_external_tools(self, *, source_prefix: str) -> int:
        """按 source 前缀移除外部工具（用于 MCP reload）。"""
        sp = str(source_prefix or "")
        to_del = [
            name
            for name, meta in self._external_tool_schemas.items()
            if str(meta.get("source", "")).startswith(sp)
        ]
        for name in to_del:
            self._external_tool_schemas.pop(name, None)
            self._external_executors.pop(name, None)
        return len(to_del)

    def list_tools(self) -> Dict[str, Dict[str, Any]]:
        """返回外部工具列表（内置工具暂不统一成 schema）。"""
        return dict(self._external_tool_schemas)

    async def execute_tool(
        self,
        name: str,
        args: Optional[Dict[str, Any]] = None,
        *,
        trace_id: Optional[str] = None,
        timeout_sec: Optional[float] = None,
    ) -> Any:
        """执行外部工具（用于统一工具调用主通路的兜底路由）。"""
        from adami_kernel.observability.timeout_budget import clamp_timeout_to_budget

        key = str(name).upper().strip()
        fn = self._external_executors.get(key)
        if not fn:
            raise KeyError(f"external tool not found: {name}")
        t0 = time.perf_counter()
        timeout_sec = clamp_timeout_to_budget(timeout_sec)
        await self._emit_tool_event(
            trace_id=trace_id,
            source_module="toolbox.external",
            payload={"event_type": "TOOL_CALL_START", "tool": key, "timeout_sec": timeout_sec},
        )
        try:
            if timeout_sec is not None:
                res = await asyncio.wait_for(fn(**(args or {})), timeout=float(timeout_sec))
            else:
                res = await fn(**(args or {}))
            await self._emit_tool_event(
                trace_id=trace_id,
                source_module="toolbox.external",
                payload={
                    "event_type": "TOOL_CALL_DONE",
                    "tool": key,
                    "result": res,
                    "latency_ms": int((time.perf_counter() - t0) * 1000),
                },
            )
            return res
        except asyncio.TimeoutError:
            await self._emit_tool_event(
                trace_id=trace_id,
                source_module="toolbox.external",
                payload={
                    "event_type": "TOOL_CALL_TIMEOUT",
                    "tool": key,
                    "timeout_sec": float(timeout_sec or 0.0),
                },
            )
            raise
        except Exception as e:
            await self._emit_tool_event(
                trace_id=trace_id,
                source_module="toolbox.external",
                payload={
                    "event_type": "TOOL_CALL_ERROR",
                    "tool": key,
                    "error": type(e).__name__,
                },
            )
            raise

    # ====================== 【问题5 核心新增】独立多模态总结技能 ======================
    async def analyze_raw_media(self, raw_content: str, media_type: str = "document") -> str:
        """封装多模态总结技能（避免循环 + 走正常进化流程）"""
        if not self.router:
            return _tlsm_t("tlsm.err.no_router")

        prompt = _tlsm_t("tlsm.prompt.analyze_raw", raw_excerpt=raw_content[:4000])

        summary = await self.router.call_llm(prompt, brain_type="action", temperature=0.3)
        return summary.strip()

    # =================================================================================

    async def initialize_environment(self) -> None:
        if not os.path.exists(self.venv_dir):
            args = shlex.split(f"python3 -m venv {self.venv_dir}")
            process = await asyncio.create_subprocess_exec(*args)
            await process.communicate()

    def _get_venv_env(self) -> Dict[str, str]:
        env = os.environ.copy()
        env["VIRTUAL_ENV"] = self.venv_dir
        env["PATH"] = f"{self.venv_dir}/bin:{env.get('PATH', '')}"
        return env

    async def write_file(self, file_path: str, content: str) -> str:
        safe_path = self.fs._safe_path(file_path)

        def _write():
            with open(safe_path, "w", encoding="utf-8") as f:
                f.write(content)

        await asyncio.to_thread(_write)
        return f"Success: Wrote to {file_path}"

    async def read_file(self, file_path: str) -> str:
        safe_path = self.fs._safe_path(file_path)
        if os.path.isdir(safe_path):
            return f"Error: '{file_path}' is a directory."

        def _read():
            if not os.path.exists(safe_path):
                return "Error: File not found."
            with open(safe_path, "r", encoding="utf-8") as f:
                return f.read()

        return await asyncio.to_thread(_read)

    async def execute_command(
        self, command: str, timeout: float = 30.0, *, trace_id: Optional[str] = None
    ) -> Dict[str, Any]:
        venv_env = self._get_venv_env()
        t0 = time.perf_counter()
        await self._emit_tool_event(
            trace_id=trace_id,
            source_module="toolbox.execute_command",
            payload={"event_type": "TOOL_CALL_START", "tool": "execute_command", "timeout_sec": timeout},
        )
        try:
            args = shlex.split(command)
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.sandbox_dir,
                env=venv_env,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            out = {
                "exit_code": process.returncode,
                "stdout": stdout.decode()[:2000],
                "stderr": stderr.decode()[:2000],
            }
            await self._emit_tool_event(
                trace_id=trace_id,
                source_module="toolbox.execute_command",
                payload={
                    "event_type": "TOOL_CALL_DONE",
                    "tool": "execute_command",
                    "exit_code": out.get("exit_code"),
                    "result": dict(out),
                    "latency_ms": int((time.perf_counter() - t0) * 1000),
                },
            )
            return out
        except asyncio.TimeoutError:
            await self._emit_tool_event(
                trace_id=trace_id,
                source_module="toolbox.execute_command",
                payload={"event_type": "TOOL_CALL_TIMEOUT", "tool": "execute_command", "timeout_sec": timeout},
            )
            return {"exit_code": -1, "stdout": "", "stderr": "Execution timed out."}
        except Exception as e:
            await self._emit_tool_event(
                trace_id=trace_id,
                source_module="toolbox.execute_command",
                payload={"event_type": "TOOL_CALL_ERROR", "tool": "execute_command", "error": type(e).__name__},
            )
            return {"exit_code": -1, "stdout": "", "stderr": f"Command failed or invalid: {e}"}

    async def web_search(
        self,
        query: str,
        max_results: int = 5,
        *,
        timelimit: Optional[str] = None,
        region: Optional[str] = None,
        trace_id: Optional[str] = None,
        timeout_sec: Optional[float] = 30.0,
    ) -> list[dict[str, str]]:
        t0 = time.perf_counter()
        await self._emit_tool_event(
            trace_id=trace_id,
            source_module="toolbox.web_search",
            payload={
                "event_type": "TOOL_CALL_START",
                "tool": "web_search",
                "timeout_sec": float(timeout_sec or 0.0),
            },
        )
        try:
            # Deterministic offline mode for sim/replay.
            if bool(getattr(settings, "ADAMI_SIM_OFFLINE", False)):
                rows: list[dict[str, str]] = []
                await self._emit_tool_event(
                    trace_id=trace_id,
                    source_module="toolbox.web_search",
                    payload={
                        "event_type": "TOOL_CALL_DONE",
                        "tool": "web_search",
                        "result": rows,
                        "latency_ms": int((time.perf_counter() - t0) * 1000),
                        "n_results": 0,
                    },
                )
                return rows
            coro = self.web.search(
                str(query),
                max_results=int(max_results),
                timelimit=timelimit,
                region=region,
            )
            rows = (
                await asyncio.wait_for(coro, timeout=float(timeout_sec))
                if timeout_sec is not None
                else await coro
            )
            await self._emit_tool_event(
                trace_id=trace_id,
                source_module="toolbox.web_search",
                payload={
                    "event_type": "TOOL_CALL_DONE",
                    "tool": "web_search",
                    "result": rows if isinstance(rows, list) else [],
                    "latency_ms": int((time.perf_counter() - t0) * 1000),
                    "n_results": len(rows) if isinstance(rows, list) else 0,
                },
            )
            return rows if isinstance(rows, list) else []
        except asyncio.TimeoutError:
            await self._emit_tool_event(
                trace_id=trace_id,
                source_module="toolbox.web_search",
                payload={
                    "event_type": "TOOL_CALL_TIMEOUT",
                    "tool": "web_search",
                    "timeout_sec": float(timeout_sec or 0.0),
                },
            )
            return [
                {
                    "title": _tlsm_t("webt.err.fail_title"),
                    "href": "",
                    "body": _tlsm_t("webt.err.fail_body", detail="timeout", backend="toolbox"),
                }
            ]
        except Exception as e:
            await self._emit_tool_event(
                trace_id=trace_id,
                source_module="toolbox.web_search",
                payload={"event_type": "TOOL_CALL_ERROR", "tool": "web_search", "error": type(e).__name__},
            )
            return [
                {
                    "title": _tlsm_t("webt.err.fail_title"),
                    "href": "",
                    "body": _tlsm_t("webt.err.fail_body", detail=str(e)[:120], backend="toolbox"),
                }
            ]

    async def process_multimodal(
        self,
        media_type: str,
        payload: Dict[str, Any],
        *,
        trace_id: Optional[str] = None,
        timeout_sec: Optional[float] = None,
    ) -> Dict[str, Any]:
        t0 = time.perf_counter()
        await self._emit_tool_event(
            trace_id=trace_id,
            source_module="toolbox.multimodal",
            payload={
                "event_type": "TOOL_CALL_START",
                "tool": f"multimodal.{str(media_type)}",
                "timeout_sec": float(timeout_sec or 0.0) if timeout_sec is not None else None,
            },
        )
        try:
            coro = self.multi_modal.process_input(str(media_type), dict(payload or {}))
            res = (
                await asyncio.wait_for(coro, timeout=float(timeout_sec))
                if timeout_sec is not None
                else await coro
            )
            await self._emit_tool_event(
                trace_id=trace_id,
                source_module="toolbox.multimodal",
                payload={
                    "event_type": "TOOL_CALL_DONE",
                    "tool": f"multimodal.{str(media_type)}",
                    "result": res if isinstance(res, dict) else {"type": "text", "content": str(res)},
                    "latency_ms": int((time.perf_counter() - t0) * 1000),
                },
            )
            return res if isinstance(res, dict) else {"type": "text", "content": str(res)}
        except asyncio.TimeoutError:
            await self._emit_tool_event(
                trace_id=trace_id,
                source_module="toolbox.multimodal",
                payload={
                    "event_type": "TOOL_CALL_TIMEOUT",
                    "tool": f"multimodal.{str(media_type)}",
                    "timeout_sec": float(timeout_sec or 0.0),
                },
            )
            return {"type": "text", "content": _tlsm_t("mmodal.voice.timeout"), "task": ""}
        except Exception as e:
            await self._emit_tool_event(
                trace_id=trace_id,
                source_module="toolbox.multimodal",
                payload={
                    "event_type": "TOOL_CALL_ERROR",
                    "tool": f"multimodal.{str(media_type)}",
                    "error": type(e).__name__,
                },
            )
            return {"type": "text", "content": str(e)[:200], "task": ""}

    async def patch_cortex_tool(self, tool_filename: str, new_code: str) -> str:
        target_path = os.path.abspath(os.path.join(self.allowed_patch_dir, tool_filename))
        if not target_path.startswith(self.allowed_patch_dir) or not target_path.endswith(".py"):
            logger.warning(f"⚠️ SECURITY BLOCK: Attempted to patch out-of-bounds file {target_path}")
            return "SECURITY_BLOCK: Self-modification is strictly restricted to 'src/adami_kernel/cortex/tools/*.py'"

        try:

            def _patch():
                with open(target_path, "w", encoding="utf-8") as f:
                    f.write(new_code)

            await asyncio.to_thread(_patch)

            module_name = f"adami_kernel.cortex.tools.{tool_filename[:-3]}"
            if module_name in sys.modules:
                importlib.reload(sys.modules[module_name])
                if tool_filename == "fs_tool.py":
                    self.fs = sys.modules[module_name].FileSystemTool(self.sandbox_dir)
                if tool_filename == "web_tool.py":
                    self.web = sys.modules[module_name].WebTool(self.sandbox_dir)
                    self.web.web_search = self.web.search

            logger.info(f"🧬 [Neuroplasticity] Successfully patched and reloaded {tool_filename}")
            return f"Success: Module {module_name} patched and hot-reloaded."
        except Exception as e:
            return f"Error during hot-reload: {e}"

    # ====================== 多模态工具（已优化） ======================
    async def transcribe_voice(self, audio_path: str) -> str:
        """语音转文本（Whisper）"""
        try:
            result = await self.multi_modal.process_input("voice", {"file_path": audio_path})
            return result.get("content", _tlsm_t("tlsm.voice.default_fail"))
        except Exception as e:
            return _tlsm_t("tlsm.voice.exc", detail=str(e)[:100])

    async def analyze_image(self, image_base64: str) -> str:
        """图像理解（BLIP）—— 现在走独立技能"""
        try:
            result = await self.process_multimodal(
                "photo", {"image_base64": image_base64}, trace_id=None, timeout_sec=45.0
            )
            if isinstance(result, dict) and result.get("type") == "raw_multi_modal":
                return await self.analyze_raw_media(result.get("raw_content", ""), "photo")
            return result.get("content", _tlsm_t("tlsm.image.default_fail"))
        except Exception as e:
            return _tlsm_t("tlsm.image.exc", detail=str(e)[:100])

    async def parse_file(self, file_path: str) -> str:
        """文件解析（PDF/Word/Excel）—— 现在走独立技能"""
        try:
            result = await self.process_multimodal(
                "document", {"file_path": file_path}, trace_id=None, timeout_sec=60.0
            )
            if isinstance(result, dict) and result.get("type") == "raw_multi_modal":
                return await self.analyze_raw_media(result.get("raw_content", ""), "document")
            return result.get("content", _tlsm_t("tlsm.file.default_fail"))
        except Exception as e:
            return _tlsm_t("tlsm.file.exc", detail=str(e)[:100])

    # ============================================================================
