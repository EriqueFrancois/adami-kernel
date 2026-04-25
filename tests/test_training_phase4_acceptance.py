"""阶段 4（Agent Lightning 训练适配）验收测试。

验收方案（摘要）
----------------
AT-1  轻量导入：仅 ``adami_kernel.training`` 公共导出不得加载 ``decision_processor``（子进程中验收）。
AT-2  ``agl_bridge``：``AGL_AVAILABLE`` 为布尔；模块可重复导入。
AT-3  JSONL → TaskInput：字段与 ``ExperienceAggregator`` 落盘格式一致；``reward_hint`` / ``task`` 推导正确。
AT-4  ``EpisodeTaskDataset``：符合 AGL 0.3 ``Dataset`` Protocol（``__len__`` / ``__getitem__``）。
AT-5  ``discover_episodes_jsonl_roots``：递归发现 ``episodes.jsonl``。
AT-6  ``write_policy_bundle``：写出可校验的 ``manifest.json`` + 模板，checksum 匹配。
AT-7  CLI ``main``：空经验目录 exit code 3；未装 AGL 时 exit code 2（在子进程隔离测或未装时 skip）。
AT-8  集成（需 ``poetry install -E training``）：``AdamiAGLLitAgent.rollout_async`` 返回 float。
AT-9  CLI ``--dry-run``：子进程写出 manifest，不启动 Trainer（稳定、快速）。
AT-10 无 AGL 时：提供非空 JSONL 且非 dry-run → exit 2；``--dry-run`` → exit 0（在未装 extra 的环境验证）。

执行：``poetry run pytest tests/test_training_phase4_acceptance.py -v``
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

from adami_kernel.policy.loader import load_manifest
from adami_kernel.training.agl_bridge import AGL_AVAILABLE
from adami_kernel.training.experience_to_rollouts import (
    EpisodeTaskDataset,
    ExperienceEpisode,
    build_dataset_from_episode_paths,
    build_task_input_from_episode,
    discover_episodes_jsonl_roots,
    load_episodes_from_jsonl,
)
from adami_kernel.training.run_trainer import main as run_trainer_main
from adami_kernel.training.run_trainer import write_policy_bundle


def test_at1_hasattr_and_idempotent_agl_bridge() -> None:
    from adami_kernel.training import agl_bridge

    assert isinstance(agl_bridge.AGL_AVAILABLE, bool)
    from adami_kernel.training import agl_bridge as again

    assert again.AGL_AVAILABLE is agl_bridge.AGL_AVAILABLE


def test_at1_subprocess_training_import_no_decision_processor() -> None:
    code = """
import sys
from adami_kernel.training import AGL_AVAILABLE
from adami_kernel.training.experience_to_rollouts import ExperienceEpisode
assert "adami_kernel.cortex.decision_processor" not in sys.modules
print("ok")
"""
    r = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "ok" in r.stdout


def test_at3_task_input_from_episode_roundtrip() -> None:
    ep = ExperienceEpisode(
        episode_id="ep_at3",
        primary_trace_id="trace_at3",
        status="success",
        meta={"chat_id": "room1", "task": "explicit task"},
        events=[
            {
                "trace_id": "t1",
                "episode_id": "ep_at3",
                "type": "llm_turn",
                "payload": {"prompt_summary": "should not win"},
            },
            {
                "trace_id": "t2",
                "episode_id": "ep_at3",
                "type": "feedback",
                "payload": {"reward": 0.75, "source": "test"},
            },
        ],
    )
    ti = build_task_input_from_episode(ep)
    assert ti["episode_id"] == "ep_at3"
    assert ti["primary_trace_id"] == "trace_at3"
    assert ti["chat_id"] == "room1"
    assert ti["task"] == "explicit task"
    assert ti["reward_hint"] == 0.75
    assert ti["replay_status"] == "success"
    assert ti["events_digest"] == {"llm_turn": 1, "tool_call": 0, "feedback": 1}


def test_at3_infer_task_from_llm_when_meta_empty() -> None:
    ep = ExperienceEpisode(
        episode_id="ep2",
        primary_trace_id="tr2",
        status="success",
        meta={},
        events=[
            {
                "type": "llm_turn",
                "trace_id": "x",
                "episode_id": "ep2",
                "payload": {"prompt_summary": "  summarize this  "},
            },
        ],
    )
    ti = build_task_input_from_episode(ep)
    assert ti["task"] == "summarize this"


def test_at4_episode_task_dataset() -> None:
    ds = EpisodeTaskDataset([{"id": 1}, {"id": 2}])
    assert len(ds) == 2
    assert ds[0]["id"] == 1
    assert ds[1]["id"] == 2


def test_at5_discover_and_load_jsonl(tmp_path: Path) -> None:
    day = tmp_path / "2026-01-15"
    day.mkdir(parents=True)
    ep = ExperienceEpisode(
        episode_id="e_disc",
        primary_trace_id="p_disc",
        status="success",
        meta={},
        events=[],
    )
    (day / "episodes.jsonl").write_text(ep.model_dump_json() + "\n", encoding="utf-8")
    roots = discover_episodes_jsonl_roots(tmp_path)
    assert len(roots) == 1
    loaded = load_episodes_from_jsonl(roots[0])
    assert len(loaded) == 1
    assert loaded[0].episode_id == "e_disc"


def test_at5_build_dataset_multi_file(tmp_path: Path) -> None:
    d1 = tmp_path / "a.jsonl"
    d2 = tmp_path / "sub" / "b.jsonl"
    d2.parent.mkdir()
    e1 = ExperienceEpisode(episode_id="a", primary_trace_id="a", status="s", meta={}, events=[])
    e2 = ExperienceEpisode(episode_id="b", primary_trace_id="b", status="s", meta={}, events=[])
    paths = [d1, d2]
    paths[0].write_text(e1.model_dump_json() + "\n", encoding="utf-8")
    paths[1].write_text(e2.model_dump_json() + "\n", encoding="utf-8")
    ds = build_dataset_from_episode_paths(paths, limit=None)
    assert len(ds) == 2


def test_at6_write_policy_bundle_roundtrip(tmp_path: Path) -> None:
    out = tmp_path / "policy_out"
    write_policy_bundle(
        out, notes="training notes line", manifest_version="0.9.9", optional_model_ref="m1"
    )
    man_path = out / "manifest.json"
    assert man_path.is_file()
    m = load_manifest(out, "manifest.json")
    assert m.version == "0.9.9"
    assert m.optional_model_ref == "m1"
    assert "training_run" in m.prompt_template_paths
    rel = m.prompt_template_paths["training_run"]
    tmpl_path = out / rel
    expect = hashlib.sha256(tmpl_path.read_bytes()).hexdigest()
    assert m.checksums[rel] == expect


def test_at7_main_empty_experience_dir_exits_3(tmp_path: Path) -> None:
    empty = tmp_path / "no_jsonl_here"
    empty.mkdir()
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as excinfo:
        run_trainer_main(["--experience-dir", str(empty), "--output-dir", str(out)])
    assert excinfo.value.code == 3


@pytest.mark.skipif(AGL_AVAILABLE, reason="需要未安装 agentlightning 的环境才能验收 exit 2")
def test_at7_main_missing_agl_exits_2(tmp_path: Path) -> None:
    """未装 AGL 时，非 dry-run 在通过数据集校验后 exit 2。"""
    out = tmp_path / "out"
    exp = tmp_path / "exp" / "d"
    exp.mkdir(parents=True)
    ep = ExperienceEpisode(
        episode_id="e_need_agl",
        primary_trace_id="t",
        status="success",
        meta={},
        events=[],
    )
    (exp / "episodes.jsonl").write_text(ep.model_dump_json() + "\n", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        run_trainer_main(["--experience-dir", str(tmp_path / "exp"), "--output-dir", str(out)])
    assert excinfo.value.code == 2


@pytest.mark.skipif(not AGL_AVAILABLE, reason="需要 poetry install -E training")
@pytest.mark.asyncio
async def test_at8_adami_lit_agent_rollout_returns_float() -> None:
    from unittest.mock import MagicMock

    from adami_kernel.training.adami_agl_agent import AdamiAGLLitAgent

    agent = AdamiAGLLitAgent()
    rollout = MagicMock()
    rollout.rollout_id = "roll_r1"
    task = {
        "episode_id": "e1",
        "primary_trace_id": "t1",
        "chat_id": "agl",
        "task": "ping",
        "reward_hint": 0.42,
    }
    reward = await agent.rollout_async(task, {}, rollout)
    assert isinstance(reward, float)
    assert reward == pytest.approx(0.42)


def test_at9_dry_run_writes_manifest_subprocess(tmp_path: Path) -> None:
    """AT-9：``--dry-run`` 子进程快速写出 manifest（不依赖 Trainer 生命周期）。"""
    exp = tmp_path / "exp" / "day"
    exp.mkdir(parents=True)
    line = ExperienceEpisode(
        episode_id="e_dry",
        primary_trace_id="t_dry",
        status="success",
        meta={"task": "dry"},
        events=[],
    ).model_dump_json()
    (exp / "episodes.jsonl").write_text(line + "\n", encoding="utf-8")
    out = tmp_path / "agl_out"
    repo_root = Path(__file__).resolve().parents[1]
    cmd = [
        sys.executable,
        "-m",
        "adami_kernel.training.run_trainer",
        "--experience-dir",
        str(tmp_path / "exp"),
        "--output-dir",
        str(out),
        "--dry-run",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    mf = out / "manifest.json"
    assert mf.is_file()
    tmpl = out / "templates" / "training_run.txt"
    assert tmpl.is_file()
    assert "dry-run" in tmpl.read_text(encoding="utf-8").lower()


@pytest.mark.skipif(AGL_AVAILABLE, reason="需未安装 agentlightning 的 venv")
def test_at10_dry_run_succeeds_without_agl_subprocess(tmp_path: Path) -> None:
    """AT-10：无 AGL 时 ``--dry-run`` 仍应成功（子进程）。"""
    exp = tmp_path / "exp" / "day"
    exp.mkdir(parents=True)
    ep = ExperienceEpisode(
        episode_id="e_no_agl",
        primary_trace_id="p",
        status="success",
        meta={},
        events=[],
    )
    (exp / "episodes.jsonl").write_text(ep.model_dump_json() + "\n", encoding="utf-8")
    out = tmp_path / "out"
    repo_root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "adami_kernel.training.run_trainer",
            "--experience-dir",
            str(tmp_path / "exp"),
            "--output-dir",
            str(out),
            "--dry-run",
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.skipif(not AGL_AVAILABLE, reason="需要 poetry install -E training")
def test_at8_adami_train_agl_help() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "adami_kernel.training.run_trainer", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "--experience-dir" in proc.stdout
    assert "shared_memory" in proc.stdout
    assert "dummy" in proc.stdout
    assert "--dry-run" in proc.stdout


def test_console_script_entry_registered() -> None:
    """Poetry [tool.poetry.scripts] 注册检查（不启动训练）。"""
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    raw = pyproject.read_text(encoding="utf-8")
    assert 'adami-train-agl = "adami_kernel.training.run_trainer:main"' in raw
