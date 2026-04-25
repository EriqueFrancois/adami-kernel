"""CLI：Agent Lightning `Trainer` + `InMemoryLightningStore` + 预填 Experience JSONL。

用法::

    poetry install -E training
    adami-train-agl --experience-dir .adami_data/experience --output-dir ./agl_policy_out

未安装 ``agentlightning`` 时：使用 ``--dry-run`` 仍可校验 JSONL 并写出 manifest；真正训练需 ``poetry install -E training``。

当前 CLI 要求提供 ``--experience-dir``（至少一条 Episode JSONL）。纯在线 rollout 可在后续版本中另行暴露开关。

``run_training_job`` 供内核定时任务调用，返回整型退出码而非 ``sys.exit``。
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional, cast

from adami_kernel.config import settings
from adami_kernel.i18n import t as i18n_t
from adami_kernel.policy.manifest import PolicyManifest
from adami_kernel.training.agl_bridge import AGL_AVAILABLE, IMPORT_ERROR, agl
from adami_kernel.training.experience_to_rollouts import (
    build_dataset_from_experience_dir,
    discover_episodes_jsonl_roots,
)

logger = logging.getLogger("AdamI-RunTrainer")


def _rtrn_t(key: str, **kwargs: object) -> str:
    return i18n_t(key, locale=settings.effective_ui_default_locale(), **kwargs)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fb:
        for chunk in iter(lambda: fb.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def write_policy_bundle(
    output_dir: Path,
    *,
    notes: str,
    manifest_version: str = "0.1.0",
    optional_model_ref: Optional[str] = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    tmpl_rel = "templates/training_run.txt"
    tmpl_path = output_dir / tmpl_rel
    tmpl_path.parent.mkdir(parents=True, exist_ok=True)
    tmpl_path.write_text(notes, encoding="utf-8")
    checksums = {tmpl_rel: _sha256_file(tmpl_path)}
    manifest = PolicyManifest(
        version=manifest_version,
        prompt_template_paths={"training_run": tmpl_rel},
        checksums=checksums,
        optional_model_ref=optional_model_ref,
    )
    (output_dir / "manifest.json").write_text(
        manifest.model_dump_json(indent=2),
        encoding="utf-8",
    )


def _build_algorithm(name: str, n_epochs: int) -> Any:
    if agl is None:
        raise RuntimeError("agentlightning unavailable")
    if name == "baseline":
        from agentlightning.algorithm import Baseline

        return Baseline(
            n_epochs=n_epochs, train_split=0.9, polling_interval=0.05, max_queue_length=8
        )
    if name == "apo":
        from agentlightning.algorithm import APO

        return APO()
    raise ValueError(f"Unknown algorithm: {name}")


def run_training_job(
    *,
    experience_dir: Path,
    output_dir: Path,
    limit: Optional[int] = None,
    mode: str = "fit",
    algorithm: str = "baseline",
    n_epochs: int = 1,
    n_runners: int = 1,
    max_rollouts: Optional[int] = None,
    execution_strategy: str = "client_server",
    tracer: str = "agentops",
    manifest_version: str = "0.1.0",
    model_ref: Optional[str] = None,
    rsync_dest: Optional[str] = None,
    dry_run: bool = False,
    emit_stderr_messages: bool = True,
) -> int:
    """执行一次训练或 dry-run。返回 0 成功；2 缺少 agentlightning（完整训练）；3 无 Episode 数据。

    ``emit_stderr_messages``：为 False 时仅打日志（供内核内调度），CLI 传入 True。
    """
    roots = discover_episodes_jsonl_roots(experience_dir)
    if not roots:
        logger.warning("No episodes.jsonl under %s", experience_dir)
    train_dataset = build_dataset_from_experience_dir(
        experience_dir,
        limit=limit,
    )
    prefill_note = (
        f"Prefill: experience_dir={experience_dir.resolve()}\n"
        f"jsonl_files={len(roots)} episodes_loaded={len(train_dataset)}\n"
    )
    if len(train_dataset) == 0:
        msg = (
            "No episodes loaded from JSONL; Baseline algorithm cannot run. "
            "Check --experience-dir or collected experience data.\n"
        )
        if emit_stderr_messages:
            sys.stderr.write(msg)
        logger.warning(msg.strip())
        return 3

    if dry_run:
        write_policy_bundle(
            output_dir,
            notes="adami-train-agl dry-run (no Trainer)\n" + prefill_note,
            manifest_version=manifest_version,
            optional_model_ref=model_ref,
        )
        logger.info("Dry-run: wrote PolicyManifest -> %s", output_dir / "manifest.json")
        return 0

    if not AGL_AVAILABLE or agl is None:
        err = IMPORT_ERROR
        msg = _rtrn_t("rtrn.stderr.agl_missing", err=err)
        if emit_stderr_messages:
            sys.stderr.write(msg)
        logger.warning("agentlightning unavailable: %s", err)
        return 2

    os.environ["ADAMI_AGL_TRAIN_PROCESS"] = "1"

    from agentlightning import LitAgent, Trainer
    from agentlightning.execution import (
        ClientServerExecutionStrategy,
        SharedMemoryExecutionStrategy,
    )
    from agentlightning.store.memory import InMemoryLightningStore

    from adami_kernel.training.adami_agl_agent import AdamiAGLLitAgent

    if execution_strategy == "shared_memory":
        execution_strat: Any = SharedMemoryExecutionStrategy(n_runners=n_runners)
    else:
        execution_strat = ClientServerExecutionStrategy(n_runners=n_runners)

    algo = _build_algorithm(algorithm, n_epochs)
    store = InMemoryLightningStore(thread_safe=True)
    tracer_impl: Any = None
    if tracer == "dummy":
        from agentlightning.tracer.dummy import DummyTracer

        tracer_impl = DummyTracer()
    trainer = Trainer(
        algorithm=algo,
        store=store,
        strategy=execution_strat,
        tracer=tracer_impl,
        n_runners=n_runners,
        max_rollouts=max_rollouts,
    )
    agent = AdamiAGLLitAgent()
    started = time.time()
    lit_agent = cast(LitAgent[Any], agent)
    if mode == "dev":
        trainer.dev(lit_agent, train_dataset=train_dataset)
    else:
        trainer.fit(lit_agent, train_dataset=train_dataset)
    elapsed = time.time() - started

    notes = (
        f"adami-train-agl run\n"
        f"timestamp_utc={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n"
        f"elapsed_sec={elapsed:.3f}\n"
        f"mode={mode} algorithm={algorithm} n_epochs={n_epochs}\n" + prefill_note
    )
    write_policy_bundle(
        output_dir,
        notes=notes,
        manifest_version=manifest_version,
        optional_model_ref=model_ref,
    )
    logger.info("Wrote PolicyManifest -> %s", output_dir / "manifest.json")

    if rsync_dest:
        cmd = ["rsync", "-a", str(output_dir) + "/", rsync_dest]
        logger.info("Running: %s", " ".join(cmd))
        subprocess.run(cmd, check=False)

    return 0


def main(argv: Optional[list[str]] = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    parser = argparse.ArgumentParser(description=_rtrn_t("rtrn.cli.description"))
    parser.add_argument(
        "--experience-dir",
        type=Path,
        required=True,
        help=_rtrn_t("rtrn.cli.help.experience_dir"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help=_rtrn_t("rtrn.cli.help.output_dir"),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=_rtrn_t("rtrn.cli.help.limit"),
    )
    parser.add_argument(
        "--mode",
        choices=["fit", "dev"],
        default="fit",
        help=_rtrn_t("rtrn.cli.help.mode"),
    )
    parser.add_argument("--algorithm", choices=["baseline", "apo"], default="baseline")
    parser.add_argument("--n-epochs", type=int, default=1)
    parser.add_argument("--n-runners", type=int, default=1)
    parser.add_argument("--max-rollouts", type=int, default=None)
    parser.add_argument(
        "--execution-strategy",
        choices=["client_server", "shared_memory"],
        default="client_server",
        help=_rtrn_t("rtrn.cli.help.execution_strategy"),
    )
    parser.add_argument(
        "--tracer",
        choices=["agentops", "dummy"],
        default="agentops",
        help=_rtrn_t("rtrn.cli.help.tracer"),
    )
    parser.add_argument("--manifest-version", type=str, default="0.1.0")
    parser.add_argument("--model-ref", type=str, default=None, dest="model_ref")
    parser.add_argument(
        "--rsync-dest",
        type=str,
        default=None,
        help=_rtrn_t("rtrn.cli.help.rsync_dest"),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=_rtrn_t("rtrn.cli.help.dry_run"),
    )

    args = parser.parse_args(argv)
    code = run_training_job(
        experience_dir=args.experience_dir,
        output_dir=args.output_dir,
        limit=args.limit,
        mode=args.mode,
        algorithm=args.algorithm,
        n_epochs=args.n_epochs,
        n_runners=args.n_runners,
        max_rollouts=args.max_rollouts,
        execution_strategy=args.execution_strategy,
        tracer=args.tracer,
        manifest_version=args.manifest_version,
        model_ref=args.model_ref,
        rsync_dest=args.rsync_dest,
        dry_run=args.dry_run,
        emit_stderr_messages=True,
    )
    raise SystemExit(code)


if __name__ == "__main__":
    main()
