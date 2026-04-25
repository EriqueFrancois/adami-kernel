"""训练侧 Agent Lightning 适配（可选依赖 ``agentlightning``）。"""

from __future__ import annotations

from adami_kernel.training.agl_bridge import AGL_AVAILABLE, IMPORT_ERROR, agl
from adami_kernel.training.experience_to_rollouts import (
    EpisodeTaskDataset,
    ExperienceEpisode,
    build_dataset_from_episode_paths,
    build_dataset_from_experience_dir,
    build_task_input_from_episode,
    discover_episodes_jsonl_roots,
    load_episodes_from_jsonl,
)

__all__ = [
    "AGL_AVAILABLE",
    "IMPORT_ERROR",
    "agl",
    "EpisodeTaskDataset",
    "ExperienceEpisode",
    "build_dataset_from_episode_paths",
    "build_dataset_from_experience_dir",
    "build_task_input_from_episode",
    "discover_episodes_jsonl_roots",
    "load_episodes_from_jsonl",
]
