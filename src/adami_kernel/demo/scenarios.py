"""Guided demo scenario catalog."""

from __future__ import annotations

from adami_kernel.demo.messages import ERROR_MESSAGES
from adami_kernel.demo.models import SCENARIO_IDS, ScenarioItem

_CATALOG: dict[str, dict[str, tuple[str, str]]] = {
    "en": {
        "what-adami-can-do": (
            "What Adami can do",
            "A short overview of Adami as a kernel: channels, planning, and explicit capability limits.",
        ),
        "goal-planning": (
            "Goal planning (outline only)",
            "Turn a goal into an outline of steps. The demo does not execute those steps.",
        ),
        "analyze-problem": (
            "Analyze a simple problem",
            "Break down a user-supplied problem without calling external tools.",
        ),
        "memory-mechanism": (
            "Simulated memory",
            "Show a temporary scratchpad for this session only. Nothing is written to long-term memory.",
        ),
        "reflect-improve": (
            "Reflect and improve",
            "Critique the previous demo answer and suggest a tighter rewrite.",
        ),
        "readonly-organize": (
            "Read-only organization",
            "Restructure pasted notes. No files, mail, or network side effects.",
        ),
        "freeform": (
            "Limited freeform chat",
            "Ask within the same session, turn, and tool limits as the guided scenarios.",
        ),
    },
    "zh-CN": {
        "what-adami-can-do": (
            "Adami 能做什么",
            "简要说明 Adami 作为内核的能力：通道、规划，以及明确的能力边界。",
        ),
        "goal-planning": (
            "目标规划（仅大纲）",
            "把目标整理成步骤大纲。演示不会真正执行这些步骤。",
        ),
        "analyze-problem": (
            "分析简单问题",
            "拆解用户给出的问题，不调用外部工具。",
        ),
        "memory-mechanism": (
            "模拟记忆",
            "展示仅限本会话的临时草稿。不会写入正式长期记忆。",
        ),
        "reflect-improve": (
            "反思与改进",
            "点评上一轮演示回答，并给出更紧凑的改写建议。",
        ),
        "readonly-organize": (
            "只读整理",
            "整理用户粘贴的文本。不写文件、不发消息、不访问外网。",
        ),
        "freeform": (
            "有限自由对话",
            "与精选场景共用同一套会话、轮次和工具边界。",
        ),
    },
}


def list_scenarios(locale: str) -> list[ScenarioItem]:
    loc = locale if locale in _CATALOG else "en"
    disc = (
        ERROR_MESSAGES[loc]["disclaimer"]
        if loc in ERROR_MESSAGES
        else ERROR_MESSAGES["en"]["disclaimer"]
    )
    items: list[ScenarioItem] = []
    for sid in SCENARIO_IDS:
        title, desc = _CATALOG[loc][sid]
        items.append(ScenarioItem(id=sid, title=title, description=desc, disclaimer=disc))  # type: ignore[arg-type]
    return items
