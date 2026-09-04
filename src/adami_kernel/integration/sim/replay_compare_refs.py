from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple


@dataclass(frozen=True)
class EvalArtifacts:
    suite_json: Path
    suite_md: Path


def _run(cmd: Sequence[str], *, cwd: Path, env: Optional[dict[str, str]] = None) -> None:
    r = subprocess.run(list(cmd), cwd=str(cwd), env=env, text=True, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(
            "command failed:\n"
            f"- cwd: {cwd}\n"
            f"- cmd: {' '.join(cmd)}\n"
            f"- stdout:\n{r.stdout}\n"
            f"- stderr:\n{r.stderr}\n"
        )


def _fallback_suite_report_json(*, ref: str, reason: str, details: str) -> dict:
    return {
        "ok": False,
        "score": 0,
        "failures": [f"compat_unsupported_ref:{ref}", f"compat_reason:{reason}"],
        "traces": [],
        "compat": {"ref": ref, "mode": "fallback", "reason": reason, "details": details[:2000]},
    }


def _fallback_suite_report_md(*, ref: str, reason: str) -> str:
    return (
        "## Replay eval (compat fallback)\n\n"
        f"- Ref: `{ref}`\n"
        f"- Status: **unsupported**\n"
        f"- Reason: `{reason}`\n"
    )


def _git_root(start: Path) -> Path:
    r = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=str(start),
        text=True,
        capture_output=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"not a git repo: {r.stderr.strip()}")
    return Path(r.stdout.strip())


def _worktree_add(repo: Path, *, ref: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _run(["git", "worktree", "add", "--detach", str(path), str(ref)], cwd=repo)


def _worktree_remove(repo: Path, *, path: Path) -> None:
    # Best-effort cleanup (git may already have removed).
    try:
        _run(["git", "worktree", "remove", "--force", str(path)], cwd=repo)
    except Exception:
        shutil.rmtree(path, ignore_errors=True)


def eval_suite_at_ref(
    *,
    repo: Path,
    ref: str,
    suite_dir: Path,
    out_dir: Path,
    forbid: tuple[str, ...] = ("sk-",),
    env_overrides: Optional[dict[str, str]] = None,
) -> EvalArtifacts:
    """Check out `ref` into a temporary worktree and run `adami-replay-eval` there."""
    out_dir = out_dir if out_dir.is_absolute() else (repo / out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    wt_base = out_dir / "_worktrees"
    wt_base.mkdir(parents=True, exist_ok=True)
    wt = wt_base / f"wt_{ref.replace('/', '_').replace(':', '_')}"
    if wt.exists():
        _worktree_remove(repo, path=wt)

    env = os.environ.copy()
    env.update(env_overrides or {})

    # The trace pack is treated as an input dataset and may not be committed in git.
    # Always resolve to an absolute path in the *current* filesystem.
    suite_abs = suite_dir
    if not suite_abs.is_absolute():
        suite_abs = (repo / suite_abs).resolve()
    if not suite_abs.is_dir():
        raise RuntimeError(f"suite_dir not found on disk: {suite_abs}")

    # If the caller requests HEAD, prefer evaluating from the current working tree.
    # This makes local workflows robust even when uncommitted changes add the eval CLI.
    if ref.strip().upper() == "HEAD":
        suite_json = out_dir / "replay_eval_suite.HEAD.json"
        suite_md = out_dir / "replay_eval_suite.HEAD.md"
        env_repo = dict(env)
        src_path_repo = str((repo / "src").resolve())
        existing_pp = env_repo.get("PYTHONPATH", "")
        env_repo["PYTHONPATH"] = (
            src_path_repo if not existing_pp else (src_path_repo + os.pathsep + existing_pp)
        )
        try:
            cmd = [
                sys.executable,
                "-m",
                "adami_kernel.integration.sim.replay_eval_cli",
                "--suite-dir",
                str(suite_abs),
                "--out-json",
                str(suite_json),
                "--out-md",
                str(suite_md),
            ]
            for s in forbid:
                cmd.extend(["--forbid", str(s)])
            _run(cmd, cwd=repo, env=env_repo)
            return EvalArtifacts(suite_json=suite_json, suite_md=suite_md)
        except Exception as e:
            details = str(e)
            reason = "missing_replay_eval_cli_or_install_failed"
            suite_json.write_text(
                json.dumps(
                    _fallback_suite_report_json(ref=ref, reason=reason, details=details),
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            suite_md.write_text(_fallback_suite_report_md(ref=ref, reason=reason), encoding="utf-8")
            return EvalArtifacts(suite_json=suite_json, suite_md=suite_md)

    try:
        _worktree_add(repo, ref=ref, path=wt)
        # Run replay eval using the source at that ref.
        suite_json = out_dir / f"replay_eval_suite.{ref.replace('/', '_')}.json"
        suite_md = out_dir / f"replay_eval_suite.{ref.replace('/', '_')}.md"

        # Ensure `src/` is importable even when older refs don't declare packages correctly in
        # `pyproject.toml` (or when we run without an editable install).
        env_wt = dict(env)
        src_path = str((wt / "src").resolve())
        existing_pp = env_wt.get("PYTHONPATH", "")
        env_wt["PYTHONPATH"] = (
            src_path if not existing_pp else (src_path + os.pathsep + existing_pp)
        )

        # Cross-generation compatibility:
        # - Older refs may not ship the replay eval CLI at all.
        # - In that case, write a synthetic suite report so compare can still run and report "new traces".
        try:
            # Run using the *current* interpreter and import from the worktree via PYTHONPATH.
            # This avoids relying on Poetry entrypoints or correct packaging metadata at older refs.
            cmd = [
                sys.executable,
                "-m",
                "adami_kernel.integration.sim.replay_eval_cli",
                "--suite-dir",
                str(suite_abs),
                "--out-json",
                str(suite_json),
                "--out-md",
                str(suite_md),
            ]
            for s in forbid:
                cmd.extend(["--forbid", str(s)])
            _run(cmd, cwd=wt, env=env_wt)
            return EvalArtifacts(suite_json=suite_json, suite_md=suite_md)
        except Exception as e:
            details = str(e)
            reason = "missing_replay_eval_cli_or_install_failed"
            suite_json.write_text(
                json.dumps(
                    _fallback_suite_report_json(ref=ref, reason=reason, details=details),
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            suite_md.write_text(_fallback_suite_report_md(ref=ref, reason=reason), encoding="utf-8")
            return EvalArtifacts(suite_json=suite_json, suite_md=suite_md)
    finally:
        _worktree_remove(repo, path=wt)


def compare_refs(
    *,
    baseline_ref: str,
    head_ref: str,
    suite_dir: Path,
    out_dir: Path,
    max_score_drop: int = 0,
    max_dim_drop: int = 0,
    forbid: tuple[str, ...] = ("sk-",),
) -> Tuple[Path, Path, Path, Path, str]:
    """Run baseline/head eval in isolated worktrees and generate compare artifacts.

    Returns: baseline_json, head_json, compare_json, compare_md, summary_json_text
    """
    repo = _git_root(Path.cwd())
    out_dir = out_dir if out_dir.is_absolute() else (repo / out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Keep replays deterministic in CI-like environments.
    env_overrides = {"ADAMI_MLX_ENABLED": "0"}

    base_art = eval_suite_at_ref(
        repo=repo,
        ref=baseline_ref,
        suite_dir=suite_dir,
        out_dir=out_dir / "baseline",
        forbid=forbid,
        env_overrides=env_overrides,
    )
    head_art = eval_suite_at_ref(
        repo=repo,
        ref=head_ref,
        suite_dir=suite_dir,
        out_dir=out_dir / "head",
        forbid=forbid,
        env_overrides=env_overrides,
    )

    compare_json = out_dir / "replay_compare.json"
    compare_md = out_dir / "replay_compare.md"
    cmd = [
        "poetry",
        "run",
        "python",
        "-m",
        "adami_kernel.integration.sim.replay_compare_cli",
        "--baseline-json",
        str(base_art.suite_json),
        "--head-json",
        str(head_art.suite_json),
        "--max-score-drop",
        str(int(max_score_drop)),
        "--max-dim-drop",
        str(int(max_dim_drop)),
        "--out-json",
        str(compare_json),
        "--out-md",
        str(compare_md),
    ]
    _run(cmd, cwd=repo)
    summary = compare_json.read_text(encoding="utf-8").strip()
    return base_art.suite_json, head_art.suite_json, compare_json, compare_md, summary

