# src/adami_kernel/orchestrator/agents/researcher.py
# --- START OF FILE researcher.py ---

import asyncio
import logging
import re
from typing import Any, Dict, Optional

import httpx

from adami_kernel.config import settings
from adami_kernel.cortex.claw_hub import ClawHub
from adami_kernel.cortex.tools_manager import ToolboxManager
from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.i18n import t
from adami_kernel.i18n.ui_static import catalog_pipe_tokens, task_matches_pipe_catalog
from adami_kernel.orchestrator.agent_models import AgentMessage, AgentRole

logger = logging.getLogger("AdamI-Researcher")


def _rsrc_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class Researcher:
    """
    AdamI 2.0 Researcher 代理（调研员）
    职责：网络搜索、文档解析、输出结构化摘要
    权限：只读（web_search、read_file），无写权限
    【本次核心修复】：搜索无结果时立即返回 error 消息，触发上层反思重试
    【新增】：搜索超时保护（30秒），防止无限等待
    【新增】：天气查询专用 API（wttr.in），提高天气数据获取效率
    【本次安全修复】：新增 _sanitize_web_content 防御 Prompt Injection 攻击
    【Step 3 新增】：结果缓存与中间态检查点（Checkpointing）机制
    【本次诊断强化】：在 checkpoint 命中和正常搜索成功路径返回 AgentMessage 前，输出详细消息发送诊断日志
    【本次修改】：所有返回 AgentMessage 的路径（含 error、timeout、天气等）均增加显式 target_agent=ORCHESTRATOR 日志确认，帮助定位消息丢失问题。
    """

    def __init__(self, toolbox: ToolboxManager, memory: LayeredMemory):
        self.toolbox = toolbox
        self.memory = memory

        try:
            self.claw_hub = ClawHub(toolbox) if hasattr(toolbox, "claw_hub") else None
            logger.debug(_rsrc_t("rsrc.debug.claw_ok"))
        except Exception as e:
            self.claw_hub = None
            logger.warning(_rsrc_t("rsrc.warn.claw_init", e=e))

        logger.info(_rsrc_t("rsrc.log.ready"))

    async def _load_checkpoint(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """从 LayeredMemory 读取 Researcher 的 checkpoint（summary）
        使用 workflow_state 实现严格缓存，避免重复搜索
        """
        try:
            # 使用 LayeredMemory 已有 workflow_state 机制
            checkpoint = await self.memory.get_workflow_checkpoint(workflow_id, domain="researcher")
            if checkpoint and isinstance(checkpoint, dict) and "summary" in checkpoint:
                logger.info(_rsrc_t("rsrc.log.ckpt_hit", wid=workflow_id))
                return checkpoint
            return None
        except Exception as e:  # 优雅降级
            logger.warning(_rsrc_t("rsrc.warn.ckpt_read", e=e))
            return None

    async def _save_checkpoint(
        self, workflow_id: str, summary: str, sources: list, original_task: str = ""
    ) -> None:
        """将 Researcher 结果严格保存为 checkpoint
        使用 LayeredMemory 已有 workflow_state 机制
        """
        try:
            checkpoint_data = {
                "summary": summary,
                "sources": sources[:5],  # 只保留前 5 个来源，防止过大
                "timestamp": asyncio.get_event_loop().time(),
                "status": "success",
                "original_task": original_task,
            }
            await self.memory.save_workflow_checkpoint(
                workflow_id=workflow_id, domain="researcher", data=checkpoint_data
            )
            logger.info(_rsrc_t("rsrc.log.ckpt_saved_ok", wid=workflow_id))
        except Exception as e:
            logger.warning(_rsrc_t("rsrc.warn.ckpt_save", e=e))

    def _extract_city(self, text: str) -> str:
        """
        从文本中提取城市名，支持中英文常见城市名称。
        与 executor.py 中的逻辑保持一致。
        """
        if not text:
            return None
        common_cities = list(catalog_pipe_tokens("shared.pipe.common_cities_cn"))
        for city in common_cities:
            if city in text:
                return city
        # 正则提取连续中文字符（2-4个）
        match = re.search(r"([\u4e00-\u9fff]{2,4})", text)
        return match.group(1) if match else None

    def _sanitize_web_content(self, text: str) -> str:
        """【安全补丁】免疫洗消：防御 Prompt Injection 攻击"""
        if not text:
            return ""
        # 1. 移除可能误导大模型的特殊标记符
        text = re.sub(
            r"(\[ACTION:|\[DIRECT_ANSWER\]|\[COMPLEX_TASK\]|<think>|System Override|Ignore previous instructions)",
            "[REDACTED_COMMAND]",
            text,
            flags=re.IGNORECASE,
        )
        # 2. 移除过度重复的无意义字符
        text = re.sub(r"(.)\1{10,}", r"\1\1\1", text)
        # 3. 严格限制单次返回长度，防止超长下毒撑爆上下文
        return text[:1500]

    async def process(self, msg: AgentMessage) -> AgentMessage:
        """处理 Orchestrator 下发的调研任务"""
        if msg.message_type != "task":
            # ====================== 【本次修改】显式确认 target_agent ======================
            _tgt = str(AgentRole.ORCHESTRATOR)
            _wid = str(msg.workflow_id or "")
            logger.info(
                _rsrc_t(
                    "rsrc.log.return_line",
                    tgt=_tgt,
                    wid=_wid,
                    mtype="error",
                    note=_rsrc_t("rsrc.note.ret_not_task"),
                )
            )
            # =================================================================================
            return AgentMessage(
                source_agent=AgentRole.RESEARCHER,
                target_agent=AgentRole.ORCHESTRATOR,
                message_type="error",
                payload={"error": t("eng.error.not_task")},
                workflow_id=msg.workflow_id,
                chat_id=msg.chat_id,
            )

        # 提取任务描述和原始任务
        task = msg.payload.get("task", {})
        query = task.get("description") or msg.payload.get("query", "")
        # 从 payload 中提取原始任务（可能由 Orchestrator 注入）
        original_task = msg.payload.get("result", {}).get("original_task", "")
        if not original_task:
            # 如果没找到，尝试从 task 的描述中获取（兼容旧版本）
            original_task = task.get("description", "")

        logger.info(_rsrc_t("rsrc.log.task_start", snippet=query[:80]))
        if original_task:
            logger.debug(_rsrc_t("rsrc.debug.orig_task", snippet=original_task[:80]))

        # ====================== 【Step 3 新增】Checkpoint 检查（最优先） ======================
        workflow_id = msg.workflow_id or "unknown"
        cached = await self._load_checkpoint(workflow_id)
        if cached:
            # 直接返回缓存结果，包含 original_task
            result = {
                "summary": cached["summary"],
                "sources": cached.get("sources", []),
                "raw_data": "from_checkpoint",
                "original_task": cached.get("original_task", original_task),
                "from_checkpoint": True,
            }
            # ====================== 【本次诊断强化 + 本次修改】返回前打印消息发送信息 ======================
            _tgt = str(AgentRole.ORCHESTRATOR)
            _wid = str(msg.workflow_id or "")
            logger.info(
                _rsrc_t(
                    "rsrc.log.return_line",
                    tgt=_tgt,
                    wid=_wid,
                    mtype="result",
                    note=_rsrc_t("rsrc.note.ret_from_ckpt"),
                )
            )
            # =================================================================================
            return AgentMessage(
                source_agent=AgentRole.RESEARCHER,
                target_agent=AgentRole.ORCHESTRATOR,
                message_type="result",
                payload={"result": result},
                workflow_id=msg.workflow_id,
                chat_id=msg.chat_id,
            )
        # =====================================================================

        # ====================== 新增：天气查询专用 API 路径 ======================
        if task_matches_pipe_catalog(query, "dp.intent.pipe_weather"):
            city = self._extract_city(query)
            if city:
                # 尝试调用 wttr.in 获取天气数据
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        # 使用 wttr.in 格式：%C 天气状况，%t 温度，lang=zh 中文输出
                        resp = await client.get(f"https://wttr.in/{city}?format=%C+%t&lang=zh")
                        if resp.status_code == 200:
                            weather_data = resp.text.strip()
                            if weather_data and "Unknown" not in weather_data:
                                summary = t(
                                    "researcher.weather.summary_format",
                                    city=city,
                                    weather_data=weather_data,
                                )
                                logger.info(_rsrc_t("rsrc.log.weather_ok", summary=summary))
                                result = {
                                    "summary": summary,
                                    "sources": ["wttr.in"],
                                    "raw_data": weather_data,
                                    "original_task": original_task,
                                }
                                # 存入记忆
                                await self.memory.store_experience(
                                    trace_id=msg.trace_id,
                                    domain=f"researcher_{msg.chat_id}",
                                    payload=result,
                                    chat_id=msg.chat_id,
                                )
                                # 【Step 3 新增】天气路径也保存 checkpoint
                                await self._save_checkpoint(
                                    workflow_id, summary, ["wttr.in"], original_task
                                )
                                # ====================== 【本次修改】显式确认 target_agent ======================
                                _tgt = str(AgentRole.ORCHESTRATOR)
                                _wid = str(msg.workflow_id or "")
                                logger.info(
                                    _rsrc_t(
                                        "rsrc.log.return_line",
                                        tgt=_tgt,
                                        wid=_wid,
                                        mtype="result",
                                        note=_rsrc_t("rsrc.note.ret_weather"),
                                    )
                                )
                                # =================================================================================
                                return AgentMessage(
                                    source_agent=AgentRole.RESEARCHER,
                                    target_agent=AgentRole.ORCHESTRATOR,
                                    message_type="result",
                                    payload={"result": result},
                                    workflow_id=msg.workflow_id,
                                    chat_id=msg.chat_id,
                                )
                except Exception as e:
                    logger.warning(_rsrc_t("rsrc.warn.weather_fail", e=e))
        # =====================================================================

        try:
            # 执行通用搜索，加入超时控制（30秒）
            if hasattr(self.toolbox, "web"):
                search_result = await asyncio.wait_for(self.toolbox.web.search(query), timeout=30.0)
            else:
                search_result = []

            # 无结果时立即返回错误
            if not search_result or (isinstance(search_result, list) and len(search_result) == 0):
                logger.warning(_rsrc_t("rsrc.warn.search_empty", q=query))
                # ====================== 【本次修改】显式确认 target_agent ======================
                _tgt = str(AgentRole.ORCHESTRATOR)
                _wid = str(msg.workflow_id or "")
                logger.info(
                    _rsrc_t(
                        "rsrc.log.return_line",
                        tgt=_tgt,
                        wid=_wid,
                        mtype="error",
                        note=_rsrc_t("rsrc.note.ret_no_hits"),
                    )
                )
                # =================================================================================
                return AgentMessage(
                    source_agent=AgentRole.RESEARCHER,
                    target_agent=AgentRole.ORCHESTRATOR,
                    message_type="error",
                    payload={"error": f"Web search yielded no results for query: {query}"},
                    workflow_id=msg.workflow_id,
                    chat_id=msg.chat_id,
                )

            # 处理结果 + 免疫洗消
            if isinstance(search_result, list):
                if search_result:
                    item = search_result[0]
                    raw_summary = item.get("summary") if isinstance(item, dict) else str(item)
                    # 执行洗消
                    summary = self._sanitize_web_content(raw_summary)
                    sources = [
                        item.get("url") or item.get("link") or "web"
                        for item in search_result[:3]
                        if isinstance(item, dict)
                    ]
                else:
                    summary = t("researcher.error.no_search_results")
                    sources = []
            elif isinstance(search_result, dict):
                # 执行洗消
                summary = self._sanitize_web_content(
                    search_result.get("summary", t("researcher.fallback.summary_done"))
                )
                sources = search_result.get("sources", ["web_search"])
            else:
                summary = self._sanitize_web_content(str(search_result))
                sources = ["web_search"]

            logger.info(_rsrc_t("rsrc.log.sanitize", n=len(summary)))

            # 结构化输出，包含原始任务
            result = {
                "summary": summary,
                "sources": sources,
                "raw_data": search_result,
                "original_task": original_task,  # 传递原始任务，供下游使用
            }

            # ====================== 【Step 3 新增】成功后立即保存 checkpoint ======================
            await self._save_checkpoint(workflow_id, summary, sources, original_task)
            # =====================================================================

            # ====================== 【本次诊断强化 + 本次修改】返回前打印消息发送信息 ======================
            _tgt = str(AgentRole.ORCHESTRATOR)
            _wid = str(msg.workflow_id or "")
            logger.info(
                _rsrc_t(
                    "rsrc.log.return_line",
                    tgt=_tgt,
                    wid=_wid,
                    mtype="result",
                    note=_rsrc_t(
                        "rsrc.note.ret_result_keys",
                        keys=",".join(list(result.keys())),
                    ),
                )
            )
            # =================================================================================

            # 存入记忆
            await self.memory.store_experience(
                trace_id=msg.trace_id,
                domain=f"researcher_{msg.chat_id}",
                payload=result,
                chat_id=msg.chat_id,
            )

            return AgentMessage(
                source_agent=AgentRole.RESEARCHER,
                target_agent=AgentRole.ORCHESTRATOR,
                message_type="result",
                payload={"result": result},
                workflow_id=msg.workflow_id,
                chat_id=msg.chat_id,
            )

        except asyncio.TimeoutError:
            logger.warning(_rsrc_t("rsrc.warn.search_timeout", q=query))
            # ====================== 【本次修改】显式确认 target_agent ======================
            _tgt = str(AgentRole.ORCHESTRATOR)
            _wid = str(msg.workflow_id or "")
            logger.info(
                _rsrc_t(
                    "rsrc.log.return_line",
                    tgt=_tgt,
                    wid=_wid,
                    mtype="error",
                    note=_rsrc_t("rsrc.note.ret_timeout"),
                )
            )
            # =================================================================================
            return AgentMessage(
                source_agent=AgentRole.RESEARCHER,
                target_agent=AgentRole.ORCHESTRATOR,
                message_type="error",
                payload={"error": t("researcher.error.search_timeout", query=query)},
                workflow_id=msg.workflow_id,
                chat_id=msg.chat_id,
            )
        except Exception as e:
            logger.error(_rsrc_t("rsrc.err.research", e=e), exc_info=True)
            # ====================== 【本次修改】显式确认 target_agent ======================
            _tgt = str(AgentRole.ORCHESTRATOR)
            _wid = str(msg.workflow_id or "")
            logger.info(
                _rsrc_t(
                    "rsrc.log.return_line",
                    tgt=_tgt,
                    wid=_wid,
                    mtype="error",
                    note=_rsrc_t("rsrc.note.ret_exc"),
                )
            )
            # =================================================================================
            return AgentMessage(
                source_agent=AgentRole.RESEARCHER,
                target_agent=AgentRole.ORCHESTRATOR,
                message_type="error",
                payload={"error": str(e)},
                workflow_id=msg.workflow_id,
                chat_id=msg.chat_id,
            )


# --- END OF FILE src/adami_kernel/orchestrator/agents/researcher.py ---
