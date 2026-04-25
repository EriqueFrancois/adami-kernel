"""内核内定时训练：按配置的本地时区「每天固定整点」触发一次 ``run_training_job``。

与 ``AutonomicNervousSystem`` 的「固定间隔」不同，此处使用墙钟时间（如北京时间 03:00）。
训练在 ``asyncio.to_thread`` 中执行，避免阻塞事件循环；重叠触发时通过 async 锁串行化。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from adami_kernel.config import settings
from adami_kernel.i18n import t
from adami_kernel.i18n.boot_msg import boot_t
from adami_kernel.training.run_trainer import run_training_job

logger = logging.getLogger("AdamI-TrainSchedule")


def _trsch_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


train_job_lock = asyncio.Lock()


def seconds_until_next_local_time(*, hour: int, minute: int, tz_name: str) -> float:
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def _resolve_output_dir() -> Path:
    if settings.ADAMI_AGL_TRAIN_OUTPUT_DIR:
        return Path(settings.ADAMI_AGL_TRAIN_OUTPUT_DIR)
    return Path(settings.resolved_policy_dir)


def run_training_job_sync_blocking() -> int:
    """在线程池中执行；根据 settings 拼装参数（定时与闲置训练共用）。"""
    experience_dir = Path(settings.resolved_experience_dir)
    output_dir = _resolve_output_dir()

    dry = bool(settings.ADAMI_TRAIN_SCHEDULE_DRY_RUN)
    if not dry and settings.ADAMI_TRAIN_SCHEDULE_FALLBACK_DRY_RUN:
        from adami_kernel.training.agl_bridge import AGL_AVAILABLE

        if not AGL_AVAILABLE:
            logger.info(boot_t("boot.log.train_schedule_agentlightning_fallback"))
            dry = True

    return run_training_job(
        experience_dir=experience_dir,
        output_dir=output_dir,
        limit=settings.ADAMI_TRAIN_SCHEDULE_LIMIT,
        mode=settings.ADAMI_TRAIN_SCHEDULE_MODE,
        algorithm=settings.ADAMI_TRAIN_SCHEDULE_ALGORITHM,
        n_epochs=settings.ADAMI_TRAIN_SCHEDULE_N_EPOCHS,
        n_runners=settings.ADAMI_TRAIN_SCHEDULE_N_RUNNERS,
        max_rollouts=settings.ADAMI_TRAIN_SCHEDULE_MAX_ROLLOUTS,
        execution_strategy=settings.ADAMI_TRAIN_SCHEDULE_EXECUTION_STRATEGY,
        tracer=settings.ADAMI_TRAIN_SCHEDULE_TRACER,
        manifest_version=settings.ADAMI_TRAIN_SCHEDULE_MANIFEST_VERSION,
        model_ref=settings.ADAMI_TRAIN_SCHEDULE_MODEL_REF,
        rsync_dest=settings.ADAMI_TRAIN_SCHEDULE_RSYNC_DEST,
        dry_run=dry,
        emit_stderr_messages=False,
    )


async def scheduled_training_loop() -> None:
    hour = int(settings.ADAMI_TRAIN_SCHEDULE_HOUR)
    minute = int(settings.ADAMI_TRAIN_SCHEDULE_MINUTE)
    tz_name = settings.ADAMI_TRAIN_SCHEDULE_TZ
    logger.info(
        boot_t(
            "boot.log.train_schedule_started",
            tz=tz_name,
            hour=hour,
            minute=minute,
            experience=settings.resolved_experience_dir,
            output=str(_resolve_output_dir()),
        )
    )
    while True:
        delay = seconds_until_next_local_time(hour=hour, minute=minute, tz_name=tz_name)
        logger.debug(_trsch_t("trsch.debug.next_in_sec", sec=int(delay)))
        await asyncio.sleep(delay)
        async with train_job_lock:
            try:
                code = await asyncio.to_thread(run_training_job_sync_blocking)
                if code == 0:
                    logger.info(_trsch_t("trsch.log.round_ok"))
                elif code == 3:
                    logger.warning(_trsch_t("trsch.warn.skip_no_episodes", code=code))
                elif code == 2:
                    logger.warning(_trsch_t("trsch.warn.no_agentlightning", code=code))
                else:
                    logger.error(_trsch_t("trsch.err.bad_exit", code=code))
            except Exception:
                logger.exception(_trsch_t("trsch.exc.round"))
