"""Prepared (canned) demonstration copy. Never labeled live."""

from __future__ import annotations

from adami_kernel.demo.messages import error_message
from adami_kernel.demo.models import FallbackPayload, ScenarioId

_BODIES: dict[str, dict[str, tuple[str, str]]] = {
    "en": {
        "what-adami-can-do": (
            "Prepared overview",
            "Adami is a kernel that routes tasks, plans multi-step work, and talks over CLI or messengers. "
            "This page is a guided demo only: it cannot run shell commands, send messages, or read your production notes.",
        ),
        "goal-planning": (
            "Prepared plan outline",
            "1) Clarify the outcome.\n2) List constraints.\n3) Order 3–5 steps.\n4) Mark what a human must approve.\n"
            "This outline is a canned example — the demo did not execute anything.",
        ),
        "analyze-problem": (
            "Prepared analysis",
            "Restate the problem, name one assumption, and propose a smallest next check. "
            "This is a prepared example, not a live investigation.",
        ),
        "memory-mechanism": (
            "Prepared memory note",
            "A real Adami instance can persist notes in Second Brain. This demo only keeps a temporary scratchpad "
            "in memory for this browser session, then deletes it.",
        ),
        "reflect-improve": (
            "Prepared reflection",
            "A stronger answer would be shorter, name the constraint first, and avoid promising actions the demo cannot take.",
        ),
        "readonly-organize": (
            "Prepared outline",
            "- Facts\n- Open questions\n- Next human actions\nThis grouping is a canned example.",
        ),
        "freeform": (
            "Prepared reply",
            "The guided demo is at capacity or offline. This canned reply stays inside the published capability limits.",
        ),
    },
    "zh-CN": {
        "what-adami-can-do": (
            "预制概览",
            "Adami 是负责任务路由、多步规划，以及 CLI/即时通讯通道的内核。"
            "本页只是引导演示：不能执行命令、发送消息，也不能读取生产笔记。",
        ),
        "goal-planning": (
            "预制规划大纲",
            "1) 明确结果\n2) 列出约束\n3) 排出 3–5 步\n4) 标出需要人工批准的步骤\n该大纲是预制示例，演示并未执行任何步骤。",
        ),
        "analyze-problem": (
            "预制分析",
            "复述问题、指出一个假设，并给出最小的下一步核验。这是预制示例，不是实时调查。",
        ),
        "memory-mechanism": (
            "预制记忆说明",
            "正式实例可以把笔记写入 Second Brain。本演示只在当前浏览器会话的内存草稿中暂存，随后删除。",
        ),
        "reflect-improve": (
            "预制反思",
            "更好的回答应更短，先写约束，并且不承诺演示无法执行的动作。",
        ),
        "readonly-organize": (
            "预制整理",
            "- 事实\n- 待确认问题\n- 需要人工处理的事项\n这是预制示例。",
        ),
        "freeform": (
            "预制回复",
            "引导演示正忙或暂时不可用。这条预制回复仍遵守已公布的能力边界。",
        ),
    },
}


def canned_fallback(locale: str, scenario_id: ScenarioId | str, reason_code: str) -> FallbackPayload:
    loc = locale if locale in _BODIES else "en"
    sid = scenario_id if scenario_id in _BODIES[loc] else "freeform"
    title, body = _BODIES[loc][sid]
    return FallbackPayload(
        reason=error_message(locale, reason_code),
        label="canned-demo",
        title=title,
        body=body,
        scenarioId=sid,  # type: ignore[arg-type]
    )
