"""阶段 6 验收：双实例运维脚本与文档（自动化可执行部分）。

手工/运维侧（本文件不替代）：
- 真实 Mac ↔ 阿里云 rsync + SSH 连通性与权限。
- cron/systemd 定时 `adami-train-agl` 与 NFS/OSS FUSE 挂载验证。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "sync_experience.sh"
_DOC = _REPO / "docs" / "ops_dual_instance.md"
_README = _REPO / "README.md"


def _run_script(
    args: list[str],
    *,
    env: dict[str, str],
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """不继承完整 os.environ，避免本机已 export 的 ADAMI_* 干扰断言。"""
    home = os.environ.get("HOME") or str(Path.home())
    full: dict[str, str] = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": home,
        "LANG": os.environ.get("LANG", "C.UTF-8"),
    }
    full.update(env)
    return subprocess.run(
        [str(_SCRIPT), *args],
        cwd=str(cwd or _REPO),
        env=full,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_p6_doc_ops_dual_instance_exists_and_covers_contract() -> None:
    """P6-DOC：运维说明存在且包含双实例角色与策略共享方式。"""
    assert _DOC.is_file(), f"missing {_DOC}"
    text = _DOC.read_text(encoding="utf-8")
    for needle in (
        "实例 A",
        "实例 B",
        "adami-train-agl",
        "ADAMI_EXPERIENCE_DIR",
        "ADAMI_POLICY_DIR",
        "sync_experience",
        "NFS",
        "rsync",
    ):
        assert needle in text, f"docs missing {needle!r}"


def test_p6_readme_links_dual_instance_doc() -> None:
    """P6-README：根 README 指向双实例文档与脚本。"""
    body = _README.read_text(encoding="utf-8")
    assert "docs/ops_dual_instance.md" in body
    assert "scripts/sync_experience.sh" in body


def test_p6_script_bash_syntax() -> None:
    """P6-SYN：`bash -n` 通过。"""
    assert _SCRIPT.is_file()
    bash = shutil.which("bash") or "/bin/bash"
    r = subprocess.run(
        [bash, "-n", str(_SCRIPT)],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert r.returncode == 0, r.stderr


def test_p6_script_requires_action() -> None:
    """P6-ARG：无子命令时退出 1 并打印用法。"""
    r = _run_script([], env={})
    assert r.returncode == 1
    assert "用法" in r.stderr or "push-experience" in r.stderr


def test_p6_script_requires_remote() -> None:
    """P6-ENV：未设置 ADAMI_SYNC_REMOTE 时退出 1。"""
    r = _run_script(["push-experience"], env={"ADAMI_SYNC_REMOTE_BASE": "/base"})
    assert r.returncode == 1
    assert "ADAMI_SYNC_REMOTE" in r.stderr


def test_p6_script_requires_remote_base() -> None:
    """P6-ENV：未设置 ADAMI_SYNC_REMOTE_BASE 时退出 1。"""
    r = _run_script(["push-experience"], env={"ADAMI_SYNC_REMOTE": "u@host.example"})
    assert r.returncode == 1
    assert "ADAMI_SYNC_REMOTE_BASE" in r.stderr


def test_p6_script_unknown_action() -> None:
    """P6-ACT：未知子命令退出 1。"""
    r = _run_script(
        ["nope"],
        env={"ADAMI_SYNC_REMOTE": "u@h", "ADAMI_SYNC_REMOTE_BASE": "/b"},
    )
    assert r.returncode == 1
    assert "未知" in r.stderr


def test_p6_script_invokes_rsync_paths_push_experience(
    tmp_path: Path,
) -> None:
    """P6-RSYNC：push-experience 调用 rsync，且仅涉及 experience 路径（非整盘 .adami_data）。"""
    log = tmp_path / "rsync.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "rsync"
    fake.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/sh
            for a in "$@"; do printf '%s\\n' "$a"; done >>"{log}"
            exit 0
            """
        ),
        encoding="utf-8",
    )
    fake.chmod(0o755)

    local_xp = tmp_path / "experience"
    local_po = tmp_path / "policy"
    local_xp.mkdir()
    local_po.mkdir()

    env = {
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "ADAMI_SYNC_REMOTE": "ubuntu@ecs.test",
        "ADAMI_SYNC_REMOTE_BASE": "/home/ubuntu/adami_data",
        "ADAMI_EXPERIENCE_DIR": str(local_xp),
        "ADAMI_POLICY_DIR": str(local_po),
    }
    r = _run_script(["push-experience"], env=env)
    assert r.returncode == 0, r.stderr + r.stdout

    joined = log.read_text(encoding="utf-8")
    assert f"{local_xp}/" in joined
    assert "ubuntu@ecs.test:/home/ubuntu/adami_data/experience/" in joined
    assert "l2_memory" not in joined and "sqlite" not in joined.lower()


def test_p6_script_dry_run_and_delete_flags(tmp_path: Path) -> None:
    """P6-FLAGS：--dry-run 与 RSYNC_DELETE=1 传入 rsync。"""
    log = tmp_path / "rsync.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "rsync"
    fake.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/sh
            for a in "$@"; do printf '%s\\n' "$a"; done >>"{log}"
            exit 0
            """
        ),
        encoding="utf-8",
    )
    fake.chmod(0o755)

    local_xp = tmp_path / "e"
    local_po = tmp_path / "p"
    local_xp.mkdir()
    local_po.mkdir()

    base_env = {
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "ADAMI_SYNC_REMOTE": "u@h",
        "ADAMI_SYNC_REMOTE_BASE": "/r",
        "ADAMI_EXPERIENCE_DIR": str(local_xp),
        "ADAMI_POLICY_DIR": str(local_po),
    }

    log.unlink(missing_ok=True)
    r = _run_script(["pull-policy", "--dry-run"], env=base_env)
    assert r.returncode == 0
    assert "--dry-run" in log.read_text(encoding="utf-8")

    log.unlink(missing_ok=True)
    r2 = _run_script(
        ["push-policy"],
        env={**base_env, "RSYNC_DELETE": "1"},
    )
    assert r2.returncode == 0
    assert "--delete" in log.read_text(encoding="utf-8")


def test_p6_script_custom_ssh_rsh(tmp_path: Path) -> None:
    """P6-SSH：ADAMI_SSH 整串作为 rsync -e 参数。"""
    log = tmp_path / "rsync.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "rsync"
    fake.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/sh
            for a in "$@"; do printf '%s\\n' "$a"; done >>"{log}"
            exit 0
            """
        ),
        encoding="utf-8",
    )
    fake.chmod(0o755)

    local_xp = tmp_path / "e"
    local_po = tmp_path / "p"
    local_xp.mkdir()
    local_po.mkdir()

    rsh = "ssh -i /tmp/fake_key -o IdentitiesOnly=yes"
    env = {
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "ADAMI_SYNC_REMOTE": "u@h",
        "ADAMI_SYNC_REMOTE_BASE": "/r",
        "ADAMI_EXPERIENCE_DIR": str(local_xp),
        "ADAMI_POLICY_DIR": str(local_po),
        "ADAMI_SSH": rsh,
    }
    r = _run_script(["push-experience"], env=env)
    assert r.returncode == 0
    lines = log.read_text(encoding="utf-8").strip().splitlines()
    assert "-e" in lines
    assert rsh in lines


def test_p6_script_push_both_two_invocations(tmp_path: Path) -> None:
    """P6-BOTH：push-both 对 experience 与 policy 各调用一次 rsync。"""
    log = tmp_path / "rsync.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "rsync"
    fake.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/sh
            echo "---" >>"{log}"
            for a in "$@"; do printf '%s\\n' "$a"; done >>"{log}"
            exit 0
            """
        ),
        encoding="utf-8",
    )
    fake.chmod(0o755)

    local_xp = tmp_path / "exp_here"
    local_po = tmp_path / "pol_here"
    local_xp.mkdir()
    local_po.mkdir()

    env = {
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "ADAMI_SYNC_REMOTE": "user@host",
        "ADAMI_SYNC_REMOTE_BASE": "/data",
        "ADAMI_EXPERIENCE_DIR": str(local_xp),
        "ADAMI_POLICY_DIR": str(local_po),
    }
    r = _run_script(["push-both"], env=env)
    assert r.returncode == 0
    body = log.read_text(encoding="utf-8")
    assert body.count("---") == 2
    assert "/data/experience/" in body
    assert "/data/policy/" in body
