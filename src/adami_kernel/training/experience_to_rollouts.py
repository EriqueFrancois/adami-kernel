"""将 ExperienceAggregator 落盘的 JSONL Episode 转为 Agent Lightning 0.3 兼容的 TaskInput 与 Dataset。

对照 `agentlightning.types`（Bird's Eye View）：

- **TaskInput** 在 0.3 中为 ``Any``；本协议使用结构化 ``dict``，字段见
  [`build_task_input_from_episode`][adami_kernel.training.experience_to_rollouts.build_task_input_from_episode]。
- **Dataset**：与 ``typing.Protocol`` 一致，实现 ``__len__`` / ``__getitem__`` 即可
 （与 PyTorch Dataset 表面同构），见 [`EpisodeTaskDataset`][adami_kernel.training.experience_to_rollouts.EpisodeTaskDataset]。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, SupportsIndex, Union, cast

from pydantic import BaseModel, Field


class ExperienceEpisode(BaseModel):
    """与 `ExperienceAggregator.finalize_episode` 写入的单行 JSON 对齐。"""

    episode_id: str
    primary_trace_id: Optional[str] = None
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    status: str = ""
    meta: Dict[str, Any] = Field(default_factory=dict)
    events: List[Dict[str, Any]] = Field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]


def iter_jsonl_lines(path: Path) -> Iterator[str]:
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield line


def load_episodes_from_jsonl(path: Path) -> List[ExperienceEpisode]:
    """读取单个 jsonl 文件中的 Episode 列表。"""
    out: List[ExperienceEpisode] = []
    for raw in iter_jsonl_lines(path):
        out.append(ExperienceEpisode.model_validate_json(raw))
    return out


def discover_episodes_jsonl_roots(base: Union[str, Path]) -> List[Path]:
    """在目录树下查找 ``episodes.jsonl``（与 Telemetry 默认按日目录一致）。"""
    root = Path(base)
    if root.is_file() and root.name == "episodes.jsonl":
        return [root]
    if not root.is_dir():
        return []
    return sorted(root.rglob("episodes.jsonl"))


def _last_feedback_reward(events: List[Dict[str, Any]]) -> Optional[float]:
    for ev in reversed(events):
        if ev.get("type") != "feedback":
            continue
        payload = cast(Dict[str, Any], ev.get("payload") or {})
        r = payload.get("reward")
        if r is None:
            return None
        try:
            return float(r)
        except (TypeError, ValueError):
            return None
    return None


def _infer_task_text(ep: ExperienceEpisode) -> str:
    meta = ep.meta or {}
    if isinstance(meta.get("task"), str) and meta["task"].strip():
        return meta["task"].strip()
    for ev in ep.events:
        if ev.get("type") != "llm_turn":
            continue
        payload = cast(Dict[str, Any], ev.get("payload") or {})
        ps = payload.get("prompt_summary")
        if ps:
            return str(ps).strip()
    for ev in ep.events:
        if ev.get("type") == "tool_call":
            payload = cast(Dict[str, Any], ev.get("payload") or {})
            name = payload.get("tool_name")
            if name:
                return f"tool:{name}"
    return f"episode:{ep.episode_id}"


def build_task_input_from_episode(ep: ExperienceEpisode) -> Dict[str, Any]:
    """构造一条 **TaskInput** 载荷（``dict``，键稳定供 ``AdamiAGLLitAgent`` 消费）。

    字段映射：

    - ``input`` 语义：复用 AGL ``Rollout.input`` / ``EnqueueRolloutRequest.input`` 的任意对象约定。
    - ``episode_id`` / ``primary_trace_id``：来自 Episode 顶栏。
    - ``task``：供 ``AdamiEvent.payload[\"task\"]``；由 meta 或首个 llm_turn 摘要推导。
    - ``chat_id``：来自 ``meta``，默认 ``agl_train``。
    - ``reward_hint``：末条 ``feedback`` 的标量奖励（若无则为 ``None``）。
    - ``replay_status``：Episode 结束状态（success / fatal 等）。
    - ``events_digest``：事件计数摘要，便于算法侧过滤，不保留全量 events。
    """
    n_llm = sum(1 for e in ep.events if e.get("type") == "llm_turn")
    n_tool = sum(1 for e in ep.events if e.get("type") == "tool_call")
    n_fb = sum(1 for e in ep.events if e.get("type") == "feedback")
    chat_id = str(
        ep.meta.get("chat_id") if isinstance(ep.meta.get("chat_id"), str) else "agl_train"
    )
    trace = ep.primary_trace_id or ep.episode_id
    return {
        "episode_id": ep.episode_id,
        "primary_trace_id": trace,
        "chat_id": chat_id,
        "task": _infer_task_text(ep),
        "reward_hint": _last_feedback_reward(ep.events),
        "replay_status": ep.status,
        "events_digest": {"llm_turn": n_llm, "tool_call": n_tool, "feedback": n_fb},
        "meta": dict(ep.meta),
    }


class EpisodeTaskDataset:
    """最小 **Dataset**［``__len__`` / ``__getitem__`` → TaskInput dict］。"""

    def __init__(self, items: List[Dict[str, Any]]) -> None:
        self._items = items

    def __len__(self) -> int:
        return len(self._items)

    def __getitem__(self, index: SupportsIndex) -> Dict[str, Any]:
        return self._items[int(index)]


def build_dataset_from_episode_paths(
    paths: List[Path],
    *,
    limit: Optional[int] = None,
    episode_filter: Optional[Callable[[ExperienceEpisode], bool]] = None,
) -> EpisodeTaskDataset:
    """从多个 ``episodes.jsonl`` 构造 Dataset。

    - ``limit``：最多加载的 **episode** 条数（非行数）。
    - ``episode_filter``：可选过滤（例如只要 ``status == success``）。
    """
    inputs: List[Dict[str, Any]] = []
    for path in paths:
        for ep in load_episodes_from_jsonl(path):
            if episode_filter is not None and not episode_filter(ep):
                continue
            inputs.append(build_task_input_from_episode(ep))
            if limit is not None and len(inputs) >= limit:
                return EpisodeTaskDataset(inputs)
    return EpisodeTaskDataset(inputs)


def build_dataset_from_experience_dir(
    base: Union[str, Path],
    *,
    limit: Optional[int] = None,
    episode_filter: Optional[Callable[[ExperienceEpisode], bool]] = None,
) -> EpisodeTaskDataset:
    roots = discover_episodes_jsonl_roots(base)
    return build_dataset_from_episode_paths(roots, limit=limit, episode_filter=episode_filter)
