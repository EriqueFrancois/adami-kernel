"""Bind LifecycleManager so Telegram/Discord can request a process restart."""

from __future__ import annotations

from typing import Any, Optional

_restart_target: Optional[Any] = None


def set_restart_target(target: Any) -> None:
    global _restart_target
    _restart_target = target


def request_process_restart() -> bool:
    t = _restart_target
    if t is None or not hasattr(t, "request_process_restart"):
        return False
    t.request_process_restart()
    return True


def request_process_restart_for_chat(chat_id: str, *, platform: str) -> bool:
    """
    Ask the runtime to restart, but allow the target to gate it with queue checks
    and per-platform confirmation.
    """
    t = _restart_target
    if t is None:
        return False
    fn = getattr(t, "request_process_restart_for_chat", None)
    if not callable(fn):
        return request_process_restart()
    try:
        return bool(fn(str(chat_id), str(platform)))
    except Exception:
        return False


def confirm_process_restart(chat_id: str, *, platform: str) -> bool:
    t = _restart_target
    if t is None:
        return False
    fn = getattr(t, "confirm_process_restart", None)
    if not callable(fn):
        return request_process_restart()
    try:
        return bool(fn(str(chat_id), str(platform)))
    except Exception:
        return False


def cancel_process_restart(chat_id: str) -> bool:
    t = _restart_target
    if t is None:
        return False
    fn = getattr(t, "cancel_process_restart", None)
    if not callable(fn):
        return False
    try:
        return bool(fn(str(chat_id)))
    except Exception:
        return False


def resume_task_queue(chat_id: str, *, platform: str) -> bool:
    t = _restart_target
    if t is None:
        return False
    fn = getattr(t, "resume_task_queue_for_chat", None)
    if not callable(fn):
        return False
    try:
        return bool(fn(str(chat_id), str(platform)))
    except Exception:
        return False


def discard_task_queue(chat_id: str, *, platform: str) -> bool:
    t = _restart_target
    if t is None:
        return False
    fn = getattr(t, "discard_task_queue_for_chat", None)
    if not callable(fn):
        return False
    try:
        return bool(fn(str(chat_id), str(platform)))
    except Exception:
        return False
