"""Locale-specific user-visible Demo strings (en / zh-CN)."""

from __future__ import annotations

ERROR_MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "rate_limited": "Too many demonstration requests. Please wait and try again.",
        "turn_limit": "This demonstration session has used all available turns.",
        "input_too_long": "Your message is too long for the guided demo (max 1200 characters).",
        "queue_full": "The demonstration queue is full. Showing a prepared example instead.",
        "wait_timeout": "Waited too long for a demonstration slot. Showing a prepared example instead.",
        "session_expired": "This demonstration session has expired. Start a new session.",
        "already_running": "This session already has a demonstration turn in progress.",
        "unavailable": "The guided demo is temporarily unavailable.",
        "tool_denied": "That action is not allowed in the guided demo.",
        "csrf_denied": "The demonstration request failed a security check.",
        "origin_denied": "This origin is not allowed to use the guided demo.",
        "task_timeout": "The demonstration turn timed out. Showing a prepared example instead.",
        "model_failed": "The demonstration model did not respond. Showing a prepared example instead.",
        "cancelled": "The demonstration turn was cancelled.",
        "disclaimer": "AdamI Demo is a constrained public interaction layer. It exposes only a limited subset of AdamI behavior and does not provide unrestricted access to the full runtime, tools, or production memory.",
    },
    "zh-CN": {
        "rate_limited": "演示请求过于频繁，请稍后再试。",
        "turn_limit": "本演示会话的轮次已用完。",
        "input_too_long": "输入过长（演示最多 1200 个字符）。",
        "queue_full": "演示队列已满，改为展示预制示例。",
        "wait_timeout": "等待演示名额超时，改为展示预制示例。",
        "session_expired": "演示会话已过期，请重新开始。",
        "already_running": "本会话已有进行中的演示任务。",
        "unavailable": "引导演示暂时不可用。",
        "tool_denied": "引导演示不允许该操作。",
        "csrf_denied": "演示请求未通过安全校验。",
        "origin_denied": "当前来源不允许使用引导演示。",
        "task_timeout": "演示任务超时，改为展示预制示例。",
        "model_failed": "演示模型未响应，改为展示预制示例。",
        "cancelled": "演示任务已取消。",
        "disclaimer": "AdamI Demo 是受约束的公开交互层。它只暴露有限的能力子集，不能无限制访问完整运行时、工具或生产记忆。",
    },
}


def error_message(locale: str, code: str) -> str:
    table = ERROR_MESSAGES.get(locale) or ERROR_MESSAGES["en"]
    return table.get(code) or ERROR_MESSAGES["en"].get(code, "Request failed.")
