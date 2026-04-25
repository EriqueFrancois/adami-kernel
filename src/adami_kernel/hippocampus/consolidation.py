# src/adami_kernel/hippocampus/consolidation.py
import json
import logging
import os
import re
from datetime import datetime
from typing import List, Tuple

from rich.console import Console

from adami_kernel.config import settings
from adami_kernel.cortex.tools.json_parser import extract_json_from_llm_output
from adami_kernel.i18n import t as i18n_t

logger = logging.getLogger("AdamI-Consolidation")
console = Console()


def _hcon_t(key: str, **kwargs) -> str:
    return i18n_t(key, locale=settings.effective_ui_default_locale(), **kwargs)


_OBS = "".join(json.loads(f'"\\u{h.lower()}"') for h in ("89c2", "5bdf", "ff1a"))
_CANDIDATE_LINE_RE = re.compile(
    rf"^-\s*([🟢🔴])\s*\[(\d{{4}}-\d{{2}}-\d{{2}})\]\s*{re.escape(_OBS)}(.*)$"
)


def _normalize_candidate_body(body: str) -> str:
    s = body.strip()
    s = re.sub(r"\s+", " ", s)
    return s.lower()


class SemanticConsolidator:
    """潜意识记忆压缩引擎：在 REM_Sleep 期间抽象规律，并执行遗忘（被动触发版）
    已完整适配 LayeredMemory（UnifiedMemory）—— retrieve_recent / store_experience / prune_domain 均已实现
    【阶段2 最终版】：静默偏好观察 + Candidate Loop + 聊天消息触发优化
    """

    def __init__(self, memory, router):
        self.memory = memory  # ← LayeredMemory（已包含所有旧 UnifiedMemory 方法）
        self.router = router
        self.COMPRESSION_THRESHOLD = 30  # code_ops 超过30条时触发
        self.code_ops_count = 0  # 计数器
        self.chat_observation_count = 0  # 【阶段2 新增】聊天消息观察计数器（每5条触发一次）

    def _mark_duplicate_candidates_red(self, candidates_path: str) -> None:
        """若 candidates.md 中候选「观察：」正文规范化后重复：仅保留首次为 🟢，其余改为 🔴（单文件、原地写回）。"""
        if not os.path.isfile(candidates_path):
            return
        with open(candidates_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines(keepends=True)

        indexed: List[Tuple[int, str, str, str, str]] = []
        for i, line in enumerate(lines):
            raw = line.rstrip("\r\n")
            m = _CANDIDATE_LINE_RE.match(raw)
            if not m:
                continue
            _emoji, date_s, body = m.group(1), m.group(2), m.group(3)
            key = _normalize_candidate_body(body)
            if not key:
                continue
            indexed.append((i, key, date_s, body, raw))

        if len(indexed) < 2:
            return

        first_for_key: dict[str, int] = {}
        for i, key, _date_s, _body, _raw in indexed:
            if key not in first_for_key:
                first_for_key[key] = i

        changed = False
        out: List[str] = []
        for i, line in enumerate(lines):
            raw_stripped = line.rstrip("\r\n")
            nl = line[len(raw_stripped) :]
            m = _CANDIDATE_LINE_RE.match(raw_stripped)
            if not m:
                out.append(line)
                continue
            emoji0, date_s, body = m.group(1), m.group(2), m.group(3)
            key = _normalize_candidate_body(body)
            want = "🟢" if first_for_key.get(key) == i else "🔴"
            if emoji0 != want:
                changed = True
            out.append(f"- {want} [{date_s}]{_OBS}{body}{nl}")

        if changed:
            with open(candidates_path, "w", encoding="utf-8") as f:
                f.writelines(out)
            logger.info(
                _hcon_t("hcon.log.candidates_dup", path=candidates_path),
            )

    async def increment_code_ops(self):
        """由 LayeredMemory.store_experience 在写入 code_ops 时被动调用（核心触发器）"""
        self.code_ops_count += 1
        if self.code_ops_count >= self.COMPRESSION_THRESHOLD:
            logger.info(_hcon_t("hcon.log.code_ops", n=self.code_ops_count))
            console.print(_hcon_t("hcon.console.passive_trigger"))
            await self.rem_sleep_cycle()
            self.code_ops_count = 0  # 重置

    # 【阶段2 新增】聊天消息触发偏好观察（每5条聊天消息强制扫描一次）
    async def increment_chat_observation(self):
        """由 DecisionProcessor 在处理普通聊天消息时调用，让日常对话也能触发偏好观察"""
        self.chat_observation_count += 1
        if self.chat_observation_count >= 5:
            logger.info(_hcon_t("hcon.log.chat5"))
            console.print(_hcon_t("hcon.console.chat_pref"))
            await self.rem_sleep_cycle()
            self.chat_observation_count = 0

    async def rem_sleep_cycle(self):
        """REM Sleep 压缩循环（被动 + 定时兼容）
        完全使用 LayeredMemory 提供的统一接口
        """
        history = await self.memory.retrieve_recent("code_ops", limit=50)
        if len(history) < 3:
            logger.debug(_hcon_t("hcon.debug.history_short"))

        console.print(_hcon_t("hcon.console.delta"))

        # ================== 原有法则提取逻辑（100% 保留） ==================
        history_json = json.dumps(history, ensure_ascii=False, indent=2)
        prompt = _hcon_t("hcon.prompt.dream", history_json=history_json)

        try:
            response = await self.router.call_llm(prompt, model="deepseek-chat", temperature=0.0)
            if not response:
                console.print(_hcon_t("hcon.console.no_response"))
                return

            # 提取法则（支持标记符 + 纯文本）
            insights = []
            for line in response.splitlines():
                line = line.strip()
                if line and not line.startswith("[") and len(line) > 10:
                    insights.append(line)

            if insights:
                console.print(_hcon_t("hcon.console.insights_ok"))
                for ins in insights[:3]:
                    console.print(f"[purple]  ✦ {ins}[/purple]")
                    await self.memory.store_experience("dream", "semantic_rules", {"insight": ins})

                # 激进修剪：只保留最近5条流水账
                console.print(_hcon_t("hcon.console.prune"))
                await self.memory.prune_domain("code_ops", keep_latest=5)

                # 强制刷新提示符
                console.print(_hcon_t("hcon.console.prompt_shell"), end="")
                import sys

                sys.stdout.flush()

        except Exception as e:
            logger.error(_hcon_t("hcon.err.rem_consolidation", e=e))
            console.print(_hcon_t("hcon.console.rem_error"))

        # ================== 【阶段 2 核心：静默偏好观察 + Candidate Loop】 ==================
        console.print(_hcon_t("hcon.console.pref_scan"))
        preference_prompt = _hcon_t("hcon.prompt.preference", history_json=history_json)

        try:
            pref_response = await self.router.call_llm(
                preference_prompt, brain_type="think", temperature=0.1
            )
            pref_data = extract_json_from_llm_output(pref_response)

            if pref_data and pref_data.get("candidates"):
                candidates_path = settings.path_brain_candidates_md
                if os.path.exists(candidates_path):
                    with open(candidates_path, "a", encoding="utf-8") as f:
                        for cand in pref_data["candidates"]:
                            date_str = datetime.now().strftime("%Y-%m-%d")
                            f.write(f"- 🟢 [{date_str}]{_OBS}{cand}\n")
                    console.print(
                        _hcon_t(
                            "hcon.console.pref_found",
                            count=len(pref_data["candidates"]),
                        )
                    )
                    logger.info(_hcon_t("hcon.log.pref_written", n=len(pref_data["candidates"])))
                else:
                    logger.warning(_hcon_t("hcon.warn.candidates_missing"))
        except Exception as e:
            logger.warning(_hcon_t("hcon.warn.pref_failed", e=e))
        # =================================================================

        try:
            self._mark_duplicate_candidates_red(settings.path_brain_candidates_md)
        except Exception as e:
            logger.warning(_hcon_t("hcon.warn.dup_mark_failed", e=e))

    # ====================== 兼容原有定时调用 ======================
    async def legacy_rem_sleep(self):
        """保留旧接口，供原有定时器或手动调用"""
        await self.rem_sleep_cycle()
