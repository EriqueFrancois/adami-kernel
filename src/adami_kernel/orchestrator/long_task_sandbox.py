"""
长任务隔离子进程沙箱（模块四 · 步骤 5）

在 `path_long_task_runs_dir/{workflow_id}/{run_id}/` 下执行 TOOL 命令，cwd 为该目录；
日志写入 `run.log`；`SandboxRunHandle` 供 `StageArtifact.uri_or_payload_ref` 引用。

与既有 `ToolboxManager.sandbox_dir`（.adami_sandbox）并存：此处按 run 隔离，便于对接 CI/容器时
将整个 run 目录挂载为产物卷。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Tuple

from adami_kernel.config import settings

if TYPE_CHECKING:
    from adami_kernel.cortex.tools_manager import ToolboxManager
    from adami_kernel.orchestrator.long_task_schema import StageArtifact

logger = logging.getLogger("AdamI-LongTaskSandbox")

_SAFE_SEGMENT = re.compile(r"^[a-zA-Z0-9_.\-:]+$")


def validate_path_segment(value: str, field: str, max_len: int = 220) -> str:
    """拒绝空、过长及可疑字符（防路径拼接穿越）。"""
    s = (value or "").strip()
    if not s or len(s) > max_len or not _SAFE_SEGMENT.match(s):
        raise ValueError(f"unsafe sandbox segment for {field}: {value!r}")
    return s


def safe_run_directory(root: str, workflow_id: str, run_id: str) -> str:
    """在 root 下构造 workflow_id/run_id 目录，并校验落在 root 内。"""
    wf = validate_path_segment(workflow_id, "workflow_id")
    rid = validate_path_segment(run_id, "run_id")
    root_abs = os.path.abspath(root)
    out = os.path.abspath(os.path.join(root_abs, wf, rid))
    if out != root_abs and not out.startswith(root_abs + os.sep):
        raise ValueError("sandbox path escapes root")
    return out


def artifacts_dir_uri(artifacts_dir: str) -> str:
    """file:// URI，供 StageArtifact.uri_or_payload_ref。"""
    return Path(os.path.abspath(artifacts_dir)).as_uri()


@dataclass
class SandboxRunHandle:
    run_id: str
    artifacts_dir: str
    log_path: str
    exit_code: int
    command: str


async def run_isolated_tool_command(
    toolbox: "ToolboxManager",
    command: str,
    *,
    workflow_id: str,
    timeout: float,
) -> Tuple[Dict[str, Any], SandboxRunHandle]:
    """
    在独立 run 目录执行 shell 命令；环境变量沿用 toolbox 的 venv PATH。
    返回 (与 execute_command 形状相近的 dict, handle)。
    """
    run_id = uuid.uuid4().hex[:16]
    root = str(getattr(settings, "path_long_task_runs_dir", "") or "").strip()
    if not root:
        root = os.path.abspath(".adami_data/long_task_runs")
    run_dir = safe_run_directory(root, workflow_id, run_id)
    os.makedirs(run_dir, mode=0o700, exist_ok=True)
    log_path = os.path.join(run_dir, "run.log")

    env = toolbox._get_venv_env()
    cmd_str = (command or "").strip()
    try:
        args = shlex.split(cmd_str)
    except ValueError as e:
        handle = SandboxRunHandle(
            run_id=run_id,
            artifacts_dir=run_dir,
            log_path=log_path,
            exit_code=-1,
            command=cmd_str,
        )
        err = f"Command parse error: {e}"
        await asyncio.to_thread(lambda: open(log_path, "w", encoding="utf-8").write(err + "\n"))
        return (
            {"exit_code": -1, "stdout": "", "stderr": err, "sandbox_run_id": run_id},
            handle,
        )

    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=run_dir,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        msg = "Execution timed out."
        await asyncio.to_thread(lambda: open(log_path, "w", encoding="utf-8").write(msg + "\n"))
        handle = SandboxRunHandle(
            run_id=run_id,
            artifacts_dir=run_dir,
            log_path=log_path,
            exit_code=-1,
            command=cmd_str,
        )
        return (
            {"exit_code": -1, "stdout": "", "stderr": msg, "sandbox_run_id": run_id},
            handle,
        )

    out_t = stdout_b.decode(errors="replace")
    err_t = stderr_b.decode(errors="replace")
    rc = proc.returncode if proc.returncode is not None else -1
    log_body = f"exit_code={rc}\n--- stdout ---\n{out_t}\n--- stderr ---\n{err_t}\n"

    def _write_log():
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(log_body)

    await asyncio.to_thread(_write_log)

    handle = SandboxRunHandle(
        run_id=run_id,
        artifacts_dir=run_dir,
        log_path=log_path,
        exit_code=int(rc),
        command=cmd_str,
    )
    clip = 2000
    return (
        {
            "exit_code": int(rc),
            "stdout": out_t[:clip],
            "stderr": err_t[:clip],
            "sandbox_run_id": run_id,
            "sandbox_artifacts_dir": run_dir,
            "sandbox_log_path": log_path,
        },
        handle,
    )


def stage_artifact_for_sandbox_run(
    handle: SandboxRunHandle,
    *,
    command: str,
    set_phase_test: bool,
) -> StageArtifact:
    from adami_kernel.orchestrator.long_task_schema import LongTaskPhase, StageArtifact

    phase = LongTaskPhase.TEST if set_phase_test else LongTaskPhase.CODE
    return StageArtifact(
        phase=phase,
        artifact_type="sandbox_run",
        uri_or_payload_ref=artifacts_dir_uri(handle.artifacts_dir),
        summary=f"exit={handle.exit_code} run_id={handle.run_id} cmd={command[:200]}",
        producer_agent="workflow_engine.TOOL.long_task_sandbox",
        content_hash=None,
    )
