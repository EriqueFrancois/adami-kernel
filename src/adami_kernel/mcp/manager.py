from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional, Tuple

import adami_kernel.config as config_mod
from adami_kernel.i18n.boot_msg import boot_t
from adami_kernel.mcp.config_loader import load_mcp_server_specs
from adami_kernel.mcp.docker_stdio_runner import McpDockerStdioRunner
from adami_kernel.mcp.tool_adapter import build_adami_tool_registrations, call_mcp_tool

logger = logging.getLogger("AdamI-MCP")


class McpManager:
    """加载 MCP servers 并把 tools 注册到 EvolutionEngine（tool_schemas + dynamic_skills）。"""

    def __init__(self, *, evolution_engine: Any) -> None:
        self.evolution_engine = evolution_engine
        self._runner = McpDockerStdioRunner()
        self._initialized = False
        self._lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._watch_task: Optional[asyncio.Task] = None
        # adami_tool_name -> (spec, mcp_tool_name)
        self._tool_map: Dict[str, Tuple[Any, str]] = {}
        self._registered_tools: set[str] = set()
        self._last_fingerprint: Optional[str] = None

    def _fingerprint(self) -> str:
        s = config_mod.settings
        return "|".join(
            [
                str(bool(s.ADAMI_MCP_ENABLED)),
                str(s.ADAMI_MCP_SERVERS_JSON or ""),
                ",".join([str(x) for x in (s.ADAMI_MCP_ALLOW_TOOLS or [])]),
                ",".join([str(x) for x in (s.ADAMI_MCP_DENY_TOOLS or [])]),
                str(s.ADAMI_MCP_DOCKER_NETWORK_MODE or ""),
                str(s.ADAMI_MCP_TIMEOUT_SEC),
            ]
        )

    def stop(self) -> None:
        self._stop.set()
        if self._watch_task and not self._watch_task.done():
            self._watch_task.cancel()

    def _unregister_all(self) -> None:
        # EvolutionEngine
        for name in list(self._registered_tools):
            try:
                self.evolution_engine.tool_schemas.pop(name.upper(), None)
            except Exception:
                pass
            try:
                self.evolution_engine.dynamic_skills.pop(name.upper(), None)
            except Exception:
                pass
        self._registered_tools.clear()
        self._tool_map.clear()
        self._initialized = False

        reg = getattr(self.evolution_engine, "tool_contract_registry", None)
        if reg is not None:
            try:
                reg.clear_source("mcp")
            except Exception:
                pass

        # ToolboxManager external registry
        tb = getattr(self.evolution_engine, "toolbox", None)
        if tb and hasattr(tb, "unregister_external_tools"):
            try:
                tb.unregister_external_tools(source_prefix="mcp:")
            except Exception:
                pass

    async def initialize(self) -> None:
        async with self._lock:
            if self._initialized:
                return
            if not config_mod.settings.ADAMI_MCP_ENABLED:
                logger.info(boot_t("boot.log.mcp_disabled"))
                self._initialized = True
                return
            specs = load_mcp_server_specs()
            if not specs:
                logger.info(boot_t("boot.log.mcp_no_servers"))
                self._initialized = True
                return

            for spec in specs:
                try:
                    regs = await build_adami_tool_registrations(self._runner, spec)
                except Exception as e:
                    logger.warning(
                        boot_t("boot.log.mcp_tools_list_fail", name=spec.name, detail=str(e))
                    )
                    continue
                for adami_name, schema, desc, mcp_name in regs:
                    self._tool_map[adami_name] = (spec, mcp_name)
                    # 注册到 tool registry（供 Planner 生成计划）
                    try:
                        self.evolution_engine.register_tool(
                            adami_name,
                            schema,
                            desc,
                            tool_source="mcp",
                            mcp_server=spec.name,
                            mcp_tool_name=mcp_name,
                        )
                    except Exception as e:
                        logger.warning(
                            boot_t(
                                "boot.log.mcp_register_tool_fail", tool=adami_name, detail=str(e)
                            )
                        )
                        continue
                    self._registered_tools.add(adami_name.upper())

                    async def _exec(_tool: str = adami_name, **kwargs: Any) -> Any:
                        """执行 MCP tool（失败降级为字符串错误，不中断主流程）。"""
                        try:
                            spec2, mcp_tool_name = self._tool_map[_tool]
                            return await call_mcp_tool(
                                self._runner, spec2, tool_name=mcp_tool_name, arguments=kwargs
                            )
                        except Exception as e:
                            logger.warning(
                                boot_t("boot.log.mcp_tool_invoke_warn", tool=_tool, detail=str(e))
                            )
                            return boot_t("cjk_gate.mcp_tool_call_failed", detail=str(e))

                    # 可执行函数挂到 dynamic_skills，供执行引擎调用
                    self.evolution_engine.dynamic_skills[adami_name] = _exec
                    # 同步注册到 ToolboxManager（外部工具执行主通路）
                    tb = getattr(self.evolution_engine, "toolbox", None)
                    if tb and hasattr(tb, "register_external_tools"):
                        try:
                            tb.register_external_tools(
                                source=f"mcp:{spec.name}",
                                tools=[
                                    {
                                        "name": adami_name,
                                        "json_schema": schema,
                                        "description": desc,
                                        "mcp_tool_name": mcp_name,
                                    }
                                ],
                                executors={adami_name: _exec},
                            )
                        except Exception as e:
                            logger.warning(
                                boot_t(
                                    "boot.log.mcp_toolbox_register_fail",
                                    tool=adami_name,
                                    detail=str(e),
                                )
                            )

            self._initialized = True
            logger.info("[MCP] registered %d tool(s)", len(self._tool_map))

    async def refresh(self) -> None:
        """根据最新 settings 重建 MCP tools（用于 reload 热更新）。"""
        async with self._lock:
            self._unregister_all()
        try:
            await self.initialize()
        except Exception as e:
            logger.warning(boot_t("boot.log.mcp_refresh_fail", detail=str(e)))

    async def run_background(self, poll_sec: float = 2.0) -> None:
        """后台运行：启动加载 + 监控 settings 变化并热更新。

        重要：任何异常都必须吞掉并降级，不能影响主流程（Telegram/Discord/CLI）。
        """
        try:
            self._last_fingerprint = self._fingerprint()
            await self.refresh()
            while not self._stop.is_set():
                await asyncio.sleep(poll_sec)
                fp = self._fingerprint()
                if fp != self._last_fingerprint:
                    self._last_fingerprint = fp
                    await self.refresh()
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.warning(boot_t("boot.log.mcp_background_exception", detail=str(e)))
            return
